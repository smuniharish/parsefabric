import asyncio

import pytest

from parsefabric.aggregation import EventAggregator
from parsefabric.builtins import ApplicationLogParser
from parsefabric.engine import ParseEngine
from parsefabric.errors import CapabilityError
from parsefabric.models import ParseContext
from parsefabric.partitioning import LinePartitioner
from tests.support.parsers import StatefulSequenceParser


async def _source(count: int):
    for index in range(count):
        yield f"request {index} timeout"


@pytest.mark.asyncio
async def test_sync_stream_yields_incrementally() -> None:
    result_count = 0
    async for result in ParseEngine().parse_iter(
        ApplicationLogParser(), (f"timeout {index}" for index in range(4))
    ):
        result_count += len(result.events)
    assert result_count == 4


@pytest.mark.asyncio
async def test_async_stream_respects_bounded_concurrency() -> None:
    results = [
        result
        async for result in ParseEngine().parse_async_iter(
            ApplicationLogParser(), _source(15), max_concurrency=2
        )
    ]
    assert len(results) == 15
    assert all(result.events for result in results)


@pytest.mark.asyncio
async def test_async_stream_cancellation_propagates() -> None:
    task = asyncio.create_task(
        _consume_slow_stream(ParseEngine(), ApplicationLogParser())
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _consume_slow_stream(engine, parser) -> None:
    async for _ in engine.parse_async_iter(parser, _source(1000), max_concurrency=1):
        await asyncio.sleep(1)


def test_line_partitioner_preserves_order_offsets_and_bounds() -> None:
    parser = ApplicationLogParser()
    partitions = tuple(
        LinePartitioner(max_lines=2).partition(
            ["one", "two", "three"], source_id="logs", capabilities=parser.capabilities
        )
    )
    assert [part.start_line for part in partitions] == [1, 3]
    assert [part.partition_id for part in partitions] == ["0", "1"]
    assert partitions[1].start_offset == len(b"one\ntwo\n")


@pytest.mark.asyncio
async def test_partitioned_parse_and_merge_matches_whole_input() -> None:
    lines = (
        "2026-01-01 ERROR: database timeout",
        "service down",
        "retrying connection",
        "permission denied",
        "connection refused",
    )
    parser = ApplicationLogParser()
    aggregator = EventAggregator(group_by=("message",))

    whole_result = await parser.parse("\n".join(lines), ParseContext(source_id="logs"))
    whole_summary = await aggregator.aggregate(whole_result.events)

    partial_summaries = []
    partitions = LinePartitioner(max_lines=2).partition(
        lines,
        source_id="logs",
        capabilities=parser.capabilities,
    )
    for partition in partitions:
        result = await parser.parse(
            partition.content,
            ParseContext(
                source_id=partition.source_id,
                partition_id=partition.partition_id,
                source_offset=partition.start_offset,
            ),
        )
        partial_summaries.extend(await aggregator.aggregate(result.events))

    assert await aggregator.merge(partial_summaries) == whole_summary


def test_byte_bounded_partitions_receive_unique_ids() -> None:
    partitions = tuple(
        LinePartitioner(max_lines=100, max_bytes=4).partition(
            ["a", "b", "c"],
            capabilities=ApplicationLogParser().capabilities,
        )
    )
    assert [part.partition_id for part in partitions] == ["0", "1"]
    assert [part.start_offset for part in partitions] == [0, 4]


def test_line_partitioner_rejects_stateful_and_oversize_input() -> None:
    with pytest.raises(CapabilityError):
        tuple(
            LinePartitioner().partition(
                ["one"], capabilities=StatefulSequenceParser().capabilities
            )
        )
    with pytest.raises(ValueError, match="byte limit"):
        tuple(
            LinePartitioner(max_bytes=3).partition(
                ["large"], capabilities=ApplicationLogParser().capabilities
            )
        )
