"""Parse one log line and print each event with its evidence.

Run: python examples/quickstart.py
"""

import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser


async def main() -> None:
    result = await ParseEngine().parse(
        ApplicationLogParser(),
        "2026-10-04T08:15:02Z ERROR payment gateway timed out after 30s\n",
        ParseContext(source_id="checkout.log"),
    )
    for event in result.events:
        evidence = event.evidence
        print(f"{event.event_type} ({event.severity})")
        print(f"  message: {event.attributes['message']}")
        print(
            f"  evidence: {evidence.source_id} line {evidence.line_number}, "
            f"bytes {evidence.start_offset}-{evidence.end_offset}, "
            f"pattern {evidence.pattern_name!r}, "
            f"parser {evidence.parser_name} v{evidence.parser_version}"
        )


if __name__ == "__main__":
    asyncio.run(main())
