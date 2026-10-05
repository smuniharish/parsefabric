# Quickstart

This page walks through the core workflow: parse text, read the evidence,
handle input that cannot be parsed, parse a stream, and store events
compactly. Every snippet is a complete program that you can run as is.

ParseFabric is asynchronous. Scripts start the event loop with
`asyncio.run`; inside an async application or a notebook, `await` the same
calls directly.

## Parse a document

```python
import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser

LOG = """\
2026-10-04T08:15:02Z INFO checkout started
2026-10-04T08:15:04Z ERROR payment gateway timed out after 30s
2026-10-04T08:15:09Z WARN retrying payment in 5s
"""


async def main() -> None:
    result = await ParseEngine().parse(
        ApplicationLogParser(), LOG, ParseContext(source_id="checkout.log")
    )
    for event in result.events:
        print(event.evidence.line_number, event.event_type, event.severity)


asyncio.run(main())
```

Output:

```text
2 timeout ERROR
2 error ERROR
3 retry None
3 warning WARNING
```

`ParseEngine.parse` runs a parser over one input and returns a
`ParseResult`. The application-log parser checks every line against
patterns for common failure signals (timeouts, refused connections,
authentication failures, retries and more) and for `ERROR` and `WARN`
levels. A line that matches several patterns produces several events; a line
that matches none, such as line 1, produces no event.

## Read the evidence

Every event records where it came from:

```python
import asyncio
import json

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser


async def main() -> None:
    result = await ParseEngine().parse(
        ApplicationLogParser(),
        "2026-10-04T08:15:04Z ERROR payment gateway timed out after 30s\n",
        ParseContext(source_id="checkout.log"),
    )
    print(json.dumps(result.events[0].to_dict(), indent=2))


asyncio.run(main())
```

Output:

```json
{
  "schema_version": "1",
  "event_type": "timeout",
  "attributes": {
    "message": "2026-10-04T08:15:04Z ERROR payment gateway timed out after 30s"
  },
  "timestamp": null,
  "severity": "ERROR",
  "confidence": null,
  "evidence": {
    "source_id": "checkout.log",
    "start_offset": 0,
    "end_offset": 63,
    "line_number": 1,
    "parser_name": "application-log",
    "parser_version": "1",
    "pattern_name": "timeout",
    "partition_id": null,
    "correlation_id": null
  }
}
```

| Evidence field | Meaning |
| --- | --- |
| `source_id` | The source you named in the `ParseContext` |
| `start_offset`, `end_offset` | UTF-8 byte span of the line, terminator included |
| `line_number` | 1-based line number |
| `parser_name`, `parser_version` | The parser that produced the event |
| `pattern_name` | The pattern that matched |
| `partition_id`, `correlation_id` | Set when you parse partitions or correlate work |

## Handle input that cannot be parsed

Parser failures raise by default. With `continue_on_error=True`, the engine
records the failure as a `ParseIssue` in the result instead:

```python
import asyncio

from parsefabric import ParseEngine
from parsefabric.builtins import ApplicationLogParser


async def main() -> None:
    result = await ParseEngine().parse(
        ApplicationLogParser(), b"\xff not UTF-8", continue_on_error=True
    )
    for issue in result.errors:
        print(issue.error_type, "-", issue.message)


asyncio.run(main())
```

Output:

```text
UnicodeDecodeError - 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte
```

## Parse a stream

`parse_iter` parses inputs from any iterable or async iterable, one at a
time, and yields one result per input in input order:

```python
import asyncio

from parsefabric import ParseEngine
from parsefabric.builtins import ApplicationLogParser

LINES = ["request 1 timed out", "request 2 completed", "connection refused by db-1"]


async def main() -> None:
    engine = ParseEngine()
    async for result in engine.parse_iter(ApplicationLogParser(), LINES):
        print([event.event_type for event in result.events])


asyncio.run(main())
```

Output:

```text
['timeout']
[]
['connection_failure']
```

To parse several inputs at once, use `parse_async_iter` with
`max_concurrency`; it yields results in completion order. See
[Streaming and execution](../guide/execution.md).

## Store and restore events

Aggregation groups repeated events into compact evidence without losing any
of them. The aggregates serialize to JSON and rebuild the exact original
events:

```python
import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser

LOG = "database timeout\n" * 3 + "service down\n"


async def main() -> None:
    engine = ParseEngine()
    parser = ApplicationLogParser()
    context = ParseContext(source_id="db.log")
    result = await engine.parse(parser, LOG, context)

    aggregates = await engine.aggregate(parser, result.events)
    stored = parser.serialize(aggregates)
    print(f"{len(result.events)} events in {len(aggregates)} aggregates")
    for aggregate in aggregates:
        for group in aggregate.groups:
            for entry in group.evidence:
                print(aggregate.event_type, entry.occurrences, list(entry.positions))

    restored = await engine.materialize(
        parser, LOG, parser.deserialize(stored), context
    )
    print("identical:", restored == result.events)


asyncio.run(main())
```

Output:

```text
4 events in 2 aggregates
timeout 3 [1, 2, 3]
service_down 1 [4]
identical: True
```

The application-log parser is deterministic, so its aggregates store line
positions instead of whole events. `materialize` parses the source again and
verifies the result against the aggregates, checksums included. See
[Aggregation and storage](../guide/aggregation.md).

## Next steps

- Learn how results and evidence are structured in
  [Parsing and evidence](../guide/parsing.md).
- Pick a parser from the [built-in parsers](../guide/builtin-parsers.md), or
  [write your own](../guide/custom-parsers.md).
- Parse documents that mix logs, JSON and code with
  [mixed content](../guide/mixed-content.md).
- Browse the runnable [examples](../examples.md).
