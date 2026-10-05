"""Split a large log into partitions, parse them in processes and verify parity.

Run: python examples/partitioning.py
"""

import asyncio
from collections.abc import Iterable
from dataclasses import replace

from parsefabric import ParseContext, ParsedEvent, ParseEngine, ParseResult
from parsefabric.builtins import ApplicationLogParser
from parsefabric.execution import ProcessExecutionBackend
from parsefabric.partitioning import LinePartitioner, Partition

SOURCE_ID = "application.log"


def parse_partition(partition: Partition) -> tuple[int, ParseResult]:
    """Parse one partition in a worker process; offsets stay document-relative."""
    context = ParseContext(
        source_id=partition.source_id, source_offset=partition.start_offset
    )
    result = asyncio.run(ApplicationLogParser().parse(partition.content, context))
    return partition.start_line, result


def rebase(start_line: int, result: ParseResult) -> list[ParsedEvent]:
    """Turn partition-relative line numbers into document line numbers."""
    return [
        event.with_evidence(
            replace(
                event.evidence,
                line_number=start_line + (event.evidence.line_number or 1) - 1,
            )
        )
        for event in result.events
    ]


async def parse_partitioned(lines: Iterable[str]) -> tuple[int, list[ParsedEvent]]:
    """Parse ``lines`` partition by partition and check the whole-document result."""
    parser = ApplicationLogParser()
    partitions = tuple(
        LinePartitioner(max_lines=500).partition(
            lines, source_id=SOURCE_ID, capabilities=parser.capabilities
        )
    )
    async with ProcessExecutionBackend(max_workers=2) as backend:
        completed = [
            item
            async for item in backend.map(parse_partition, partitions, max_in_flight=4)
        ]
    events = [
        event
        for start_line, result in sorted(completed, key=lambda item: item[0])
        for event in rebase(start_line, result)
    ]

    source = "".join(partition.content for partition in partitions)
    engine = ParseEngine()
    context = ParseContext(source_id=SOURCE_ID)
    whole = await engine.parse(parser, source, context)
    if tuple(events) != whole.events:
        raise RuntimeError("partitioned events differ from whole-document parsing")
    aggregates = await engine.aggregate(parser, events)
    if await engine.materialize(parser, source, aggregates, context) != whole.events:
        raise RuntimeError("aggregates do not rebuild the events")
    return len(partitions), events


async def main() -> None:
    lines = ["database timeout", "service down", "connection refused"] * 1000
    partitions, events = await parse_partitioned(lines)
    print(f"{len(lines)} lines in {partitions} partitions -> {len(events)} events")
    print("identical to parsing the whole document: True")
    print("aggregates rebuild every event: True")


if __name__ == "__main__":
    asyncio.run(main())
