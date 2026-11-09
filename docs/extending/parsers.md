# Parsers

A parser turns one input into a `ParseResult`. Before writing one, check
whether a [`DeterministicParser` built from patterns](../guide/custom-parsers.md#build-a-parser-from-patterns)
covers your format: it gets line evidence, statistics and partitioning for
free.

| Base class | Implement | Use it for |
| --- | --- | --- |
| `Parser` | `name`, `version`, `capabilities`, `async parse(source, context)` | Any format, with the capabilities you can promise |
| `AsyncParser` | `async parse(source, context)`; pass `name` and `version` | Parsing that awaits I/O, such as a service call |
| `SemanticParser` | `async parse(source, context)`; pass `name`, `version` and an optional `model` | Interpretation by a [language model](language-models.md) or other non-reproducible logic |

Declare only the [capabilities](../guide/custom-parsers.md#capabilities) the
parser really has: the engine relies on them to schedule concurrent and
partitioned work and to decide whether aggregates may store line positions
instead of events.

## Subclass Parser

For formats that are not line-by-line pattern matching, subclass `Parser` and
implement `name`, `version`, `capabilities` and `parse`. Patterns remain
useful as building blocks: call `pattern.match(value)` and
`pattern.to_event(match)` yourself. This parser applies a `StructuredPattern`
to JSON access-log records:

```python
import asyncio
import json

from parsefabric import (
    Evidence,
    ParseContext,
    ParsedEvent,
    ParseEngine,
    Parser,
    ParserCapabilities,
    ParseResult,
)
from parsefabric.patterns import StructuredPattern

SLOW_REQUEST = StructuredPattern(
    "slow_request",
    lambda record: record.get("duration_ms", 0) > 1000,
    lambda record: {"path": record["path"], "duration_ms": record["duration_ms"]},
    severity="WARNING",
)

ACCESS_LOG = """\
{"path": "/cart", "status": 200, "duration_ms": 85}
{"path": "/checkout", "status": 200, "duration_ms": 2350}
{"path": "/checkout", "status": 504, "duration_ms": 30000}
"""


class AccessLogParser(Parser):
    """Report slow requests in JSON access logs, one record per line."""

    @property
    def name(self) -> str:
        return "access-log"

    @property
    def version(self) -> str:
        return "1"

    @property
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(deterministic=True, parallel_safe=True, aggregatable=True)

    async def parse(self, source: object, context: ParseContext | None = None) -> ParseResult:
        if not isinstance(source, str):
            raise TypeError("access logs must be text")
        events: list[ParsedEvent] = []
        for number, line in enumerate(source.splitlines(), start=1):
            match = SLOW_REQUEST.match(json.loads(line))
            if match is not None:
                evidence = Evidence(line_number=number, pattern_name=SLOW_REQUEST.name)
                events.append(SLOW_REQUEST.to_event(match).with_evidence(evidence))
        return ParseResult(events=tuple(events))


async def main() -> None:
    engine = ParseEngine()
    parser = AccessLogParser()
    context = ParseContext(source_id="access.log")
    result = await engine.parse(parser, ACCESS_LOG, context)
    for event in result.events:
        print(event.evidence.line_number, event.severity, event.attributes)

    aggregates = await engine.aggregate(parser, result.events)
    restored = await engine.materialize(parser, ACCESS_LOG, aggregates, context)
    print("rebuilt from line positions:", restored == result.events)


asyncio.run(main())
```

Output:

```text
2 WARNING {'path': '/checkout', 'duration_ms': 2350}
3 WARNING {'path': '/checkout', 'duration_ms': 30000}
rebuilt from line positions: True
```

The engine filled in `source_id`, `parser_name` and `parser_version`, and
because the parser declares itself deterministic, its aggregates store only
line positions. To aggregate differently, override `build_aggregator`; see
[Aggregators](aggregators.md).

## Parsers that call services or models

Derive from `AsyncParser` when parsing awaits I/O, such as a service call, and
from `SemanticParser` when a model or other non-reproducible logic interprets
the input. Both take `name` and `version` and only require `parse`. Their
capabilities make no promises about determinism or concurrency, so
aggregation retains every event and `materialize` needs no source:

```python
--8<--
examples/custom_parser.py
--8<--
```

Output:

```text
--8<-- "examples/expected/custom_parser.txt"
```

For a complete statement parser built on SQLGlot, see
[`custom_sql.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/custom_sql.py).

## Check it

```python
import asyncio

from parsefabric.builtins import ApplicationLogParser
from parsefabric.testing import check_parser


async def main() -> None:
    result = await check_parser(ApplicationLogParser(), "db timeout\nservice down\n")
    print(len(result.events), "events passed the parser contract")


asyncio.run(main())
```

```text
2 events passed the parser contract
```

`check_parser` parses the sample through the engine, checks that the result
survives a JSON round trip and that a deterministic parser repeats itself,
and, for an aggregatable parser, aggregates the events and materializes them
back. See [Test your extensions](testing.md).
