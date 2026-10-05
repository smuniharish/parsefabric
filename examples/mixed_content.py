"""Route a mixed document to existing parsers and keep every line as evidence.

Run: python examples/mixed_content.py
"""

import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import (
    ApplicationLogParser,
    JSONParser,
    MixedContentParser,
    TimestampedLogParser,
)
from parsefabric.patterns import RegexPattern

INCIDENT = """\
2026-10-01T08:00:02+00:00 ERROR shop database timeout
{"service": "shop",
 "state": "degraded"}
operator note: failover requested
```log
connection refused by replica-2
```
def retry(order):
    return gateway.charge(order)
2026-10-01T08:00:09+00:00 INFO shop database connection restored
"""


async def main() -> None:
    parser = MixedContentParser(
        routes=[
            (RegexPattern("log-line", r"^\d{4}-\d\d-\d\dT"), TimestampedLogParser()),
            (RegexPattern("json-line", r"^\{"), JSONParser()),
        ],
        fence_routes={"log": ApplicationLogParser()},
    )
    engine = ParseEngine()
    context = ParseContext(source_id="incident.md")
    result = await engine.parse(parser, INCIDENT, context)
    for event in result.events:
        evidence = event.evidence
        attributes = event.attributes
        detail = next(
            (
                attributes[key]
                for key in ("language", "message", "value", "text")
                if key in attributes
            ),
            "",
        )
        print(
            f"line {evidence.line_number:>2}: {event.event_type:<18} "
            f"{evidence.parser_name:<16} {detail}"
        )

    aggregates = await engine.aggregate(parser, result.events)
    print("aggregates:", sorted({(a.event_type, a.parser_name) for a in aggregates}))
    restored = await engine.materialize(parser, INCIDENT, aggregates, context)
    print("every event rebuilt:", restored == result.events)


if __name__ == "__main__":
    asyncio.run(main())
