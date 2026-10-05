"""Aggregate events losslessly, store them compactly and rebuild the originals.

Run: python examples/aggregation.py
"""

import asyncio
from pathlib import Path

from parsefabric import ParseContext, ParseEngine, measure_compression
from parsefabric.aggregation import EventAggregator
from parsefabric.builtins import TimestampedLogParser

SOURCE = Path(__file__).resolve().parent / "data" / "timestamped-operations.log"


def bursty_log(minutes: int) -> str:
    """A log where failures repeat in bursts, as they do during incidents."""
    lines = []
    for minute in range(minutes):
        stamp = f"2026-10-01T08:{minute:02d}"
        lines.append(f"{stamp}:00+00:00 INFO reconciliation batch started")
        lines.extend(
            f"{stamp}:{second:02d}+00:00 ERROR shop database timeout"
            for second in range(1, 41)
        )
        lines.append(f"{stamp}:41+00:00 WARN retry scheduled with a fresh connection")
    return "\n".join(lines) + "\n"


async def main() -> None:
    source = await asyncio.to_thread(SOURCE.read_text, encoding="utf-8")
    parser = TimestampedLogParser()
    engine = ParseEngine()
    context = ParseContext(source_id=SOURCE.name)
    result = await engine.parse(parser, source, context)
    print(f"{len(result.events)} events from {SOURCE.name}")

    aggregates = await engine.aggregate(parser, result.events)
    for aggregate in aggregates:
        print(f"aggregate {aggregate.event_type!r}: {aggregate.count} events")
        for group in aggregate.groups:
            for entry in group.evidence:
                print(
                    f"  {group.severity:<5} x{entry.occurrences} "
                    f"lines {list(entry.positions)} {entry.message}"
                )

    stored = parser.serialize(aggregates)
    restored = parser.deserialize(stored)
    events = await engine.materialize(parser, source, restored, context)
    print("round trip exact:", restored == aggregates and events == result.events)

    counts = await EventAggregator(group_by=("level",)).aggregate(result.events)
    print("lossy counts:", {c.key_attributes["level"]: c.count for c in counts})

    incident = bursty_log(minutes=20)
    burst = await engine.parse(parser, incident, ParseContext(source_id="incident"))
    compact = parser.serialize(await engine.aggregate(parser, burst.events))
    metrics = measure_compression(incident, compact)
    print(
        f"{len(burst.events)} bursty lines: stored {metrics.output_bytes} of "
        f"{metrics.input_bytes} bytes ({metrics.reduction_percent:.0f}% smaller, "
        f"~{metrics.tokens_saved} tokens saved)"
    )


if __name__ == "__main__":
    asyncio.run(main())
