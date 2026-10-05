"""Small stdlib benchmark for local parsing and aggregation behavior."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import tracemalloc
from collections.abc import Callable
from typing import NotRequired, TypedDict

from benchmarks._support import run_sync
from parsefabric.aggregation import EventAggregator
from parsefabric.builtins import ApplicationLogParser
from parsefabric.engine import ParseEngine
from parsefabric.execution import (
    AsyncExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.models import ParseContext, ParseResult
from parsefabric.partitioning import LinePartitioner, Partition

SCALE_RECORDS = {"small": 1_000, "medium": 10_000, "large": 100_000}


class Measurement(TypedDict):
    name: str
    wall_seconds: float
    caller_cpu_seconds: float
    caller_peak_traced_bytes: int
    event_count: NotRequired[int]
    records_per_second: NotRequired[float]
    aggregate_count: NotRequired[int]
    serialized_bytes: NotRequired[int]
    partition_count: NotRequired[int]
    checksum: NotRequired[int]


def measure[T](
    name: str,
    operation: Callable[[], T],
) -> tuple[Measurement, T]:
    tracemalloc.start()
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    try:
        value = operation()
        elapsed = time.perf_counter() - wall_start
        cpu_seconds = time.process_time() - cpu_start
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return (
        Measurement(
            name=name,
            wall_seconds=elapsed,
            caller_cpu_seconds=cpu_seconds,
            caller_peak_traced_bytes=peak_bytes,
        ),
        value,
    )


def parse_in_process(text: str) -> ParseResult:
    return run_sync(ApplicationLogParser().parse(text))


def parse_partition(partition: Partition) -> ParseResult:
    return run_sync(
        ApplicationLogParser().parse(
            partition.content,
            ParseContext(
                source_id=partition.source_id,
                partition_id=partition.partition_id,
                source_offset=partition.start_offset,
            ),
        )
    )


def cpu_heavy_parse(text: str) -> int:
    """Return a stable checksum after repeated pure-Python text processing."""
    checksum = 0
    for _ in range(8):
        for character in text:
            checksum = ((checksum << 5) - checksum + ord(character)) & 0xFFFFFFFF
    return checksum


async def execute_backend(text: str, *, process: bool) -> ParseResult:
    backend_type = ProcessExecutionBackend if process else ThreadExecutionBackend
    async with backend_type(max_workers=1) as backend:
        return await backend.run(parse_in_process, text)


async def execute_async_backend(text: str) -> ParseResult:
    async with AsyncExecutionBackend() as backend:
        return await backend.run(parse_in_process, text)


async def execute_partitioned_process(
    lines: list[str],
    parser: ApplicationLogParser,
) -> tuple[int, int]:
    event_count = 0
    partition_count = 0
    partitions = LinePartitioner(max_lines=1000).partition(
        lines,
        capabilities=parser.capabilities,
    )
    async with ProcessExecutionBackend(max_workers=2) as backend:
        async for result in backend.map(
            parse_partition,
            partitions,
            max_in_flight=4,
        ):
            event_count += len(result.events)
            partition_count += 1
    return event_count, partition_count


async def consume_async_stream(lines: list[str]) -> int:
    async def source():
        for line in lines:
            yield line

    event_count = 0
    async for result in ParseEngine().parse_async_iter(
        ApplicationLogParser(),
        source(),
        max_concurrency=32,
    ):
        event_count += len(result.events)
    return event_count


def resolve_record_count(args: argparse.Namespace, argument_parser) -> tuple[str, int]:
    if args.records is not None:
        if args.records < 1:
            argument_parser.error("--records must be positive")
        return "custom", args.records
    return args.scale, SCALE_RECORDS[args.scale]


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "--records",
        type=int,
        help="override --scale with an explicit record count",
    )
    argument_parser.add_argument(
        "--scale",
        choices=tuple(SCALE_RECORDS),
        default="medium",
        help="representative dataset size (small, medium, or large)",
    )
    args = argument_parser.parse_args()
    scale, record_count = resolve_record_count(args, argument_parser)

    lines = [
        (
            f"request {index} timeout"
            if index % 2
            else f"request {index} connection refused"
        )
        for index in range(record_count)
    ]
    text = "\n".join(lines)
    parser = ApplicationLogParser()
    measurements = []

    measurement, result = measure(
        "regex_heavy_single_input", lambda: run_sync(parser.parse(text))
    )
    measurement["event_count"] = len(result.events)
    measurement["records_per_second"] = record_count / measurement["wall_seconds"]
    measurements.append(measurement)

    async def _consume_stream() -> int:
        total = 0
        async for item in ParseEngine().parse_iter(parser, lines):
            total += len(item.events)
        return total

    def consume_stream() -> int:
        return run_sync(_consume_stream())

    measurement, stream_event_count = measure("sync_stream", consume_stream)
    measurement["event_count"] = stream_event_count
    measurement["records_per_second"] = record_count / measurement["wall_seconds"]
    measurements.append(measurement)

    measurement, async_event_count = measure(
        "async_stream",
        lambda: asyncio.run(consume_async_stream(lines)),
    )
    measurement["event_count"] = async_event_count
    measurement["records_per_second"] = record_count / measurement["wall_seconds"]
    measurements.append(measurement)

    measurement, aggregates = measure(
        "aggregation", lambda: run_sync(EventAggregator().aggregate(result.events))
    )
    measurement["aggregate_count"] = len(aggregates)
    measurements.append(measurement)

    partitioner = LinePartitioner(max_lines=1000)
    measurement, partition_count = measure(
        "partitioning",
        lambda: sum(
            1
            for _ in partitioner.partition(
                lines,
                capabilities=parser.capabilities,
            )
        ),
    )
    measurement["partition_count"] = partition_count
    measurements.append(measurement)

    measurement, partitioned_counts = measure(
        "partitioned_process_backend",
        lambda: asyncio.run(execute_partitioned_process(lines, parser)),
    )
    measurement["event_count"], measurement["partition_count"] = partitioned_counts
    measurements.append(measurement)

    measurement, payload = measure(
        "json_serialization",
        lambda: json.dumps(result.to_dict(), separators=(",", ":")),
    )
    measurement["serialized_bytes"] = len(payload.encode("utf-8"))
    measurements.append(measurement)

    for backend_name, use_process in (("thread", False), ("process", True)):
        measurement, backend_result = measure(
            f"{backend_name}_backend",
            lambda process=use_process: asyncio.run(
                execute_backend(text, process=process)
            ),
        )
        measurement["event_count"] = len(backend_result.events)
        measurements.append(measurement)

    measurement, checksum = measure("cpu_heavy_parse", lambda: cpu_heavy_parse(text))
    measurement["checksum"] = checksum
    measurements.append(measurement)

    measurement, process_checksum = measure(
        "cpu_heavy_process_backend",
        lambda: asyncio.run(_execute_cpu_heavy_process(text)),
    )
    measurement["checksum"] = process_checksum
    measurements.append(measurement)

    print(
        json.dumps(
            {
                "scale": scale,
                "records": record_count,
                "measurements": measurements,
            },
            indent=2,
        )
    )


async def _execute_cpu_heavy_process(text: str) -> int:
    async with ProcessExecutionBackend(max_workers=1) as backend:
        return await backend.run(cpu_heavy_parse, text)


if __name__ == "__main__":
    main()
