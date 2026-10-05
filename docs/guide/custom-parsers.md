# Patterns and custom parsers

When the [built-in parsers](builtin-parsers.md) do not fit your format, build
a parser from patterns, or write a parser class of your own. Either way, the
package manages aggregation and serialization, so your events get the same
lossless storage as the built-in ones.

## Patterns

A pattern is a named, prioritized rule that recognizes one kind of value and
turns a match into an event. Every pattern accepts `priority` (higher runs
first), `event_type` (defaults to the name) and `metadata` (free-form notes
that are never copied into events).

| Pattern | Matches | Event attributes |
| --- | --- | --- |
| `RegexPattern(name, expression)` | Text that the regular expression finds anywhere (`re.search`) | The named groups that took part in the match |
| `ExactPattern(name, expected)` | Values equal to `expected` | The fixed `attributes` you supply |
| `PredicatePattern(name, predicate, extractor)` | Values for which `predicate(value)` is true | `extractor(value)`, or none |
| `StructuredPattern(name, predicate, extractor)` | Mappings, such as decoded JSON objects, for which `predicate` is true | `extractor(mapping)`, or the mapping itself |

`RegexPattern`, `ExactPattern`, `PredicatePattern` and `StructuredPattern`
also accept a `severity` for the events they produce.

!!! tip "Write linear-time regular expressions"

    Patterns run on untrusted input, and Python regular expressions have no
    timeout. Anchor expressions with `^` when they describe a whole line, and
    avoid nested or overlapping quantifiers such as `(a+)+` or `.*x.*y`.

## Build a parser from patterns

`DeterministicParser` applies a set of patterns to every line of a text
document. Each line is matched against every pattern in descending priority
order (ties broken by name); each match becomes one event whose evidence
records the line number, the line's byte span and the pattern name. With
`first_match_only=True`, only the first matching pattern on each line
produces an event.

```python
--8<--
examples/custom_patterns.py
--8<--
```

Output:

```text
--8<-- "examples/expected/custom_patterns.txt"
```

`register_pattern` adds a pattern, or replaces one with the same name when
you pass `replace=True`; `unregister_pattern` removes one. The result's
`pattern_statistics` count the matches of every pattern, including those that
never matched.

A `DeterministicParser` is deterministic, incremental, parallel-safe and
line-partitionable by default. If a `PredicatePattern` callable is not
thread-safe, pass explicit `capabilities` without `parallel_safe`. A
`DeterministicParser` must stay deterministic; put non-reproducible logic in
a [parser class](#write-a-parser-class) instead.

## Capabilities

Every parser declares `ParserCapabilities`, and orchestration code checks them
before scheduling work:

| Capability | Promise | Checked by |
| --- | --- | --- |
| `deterministic` | The same input and context always produce the same result | Aggregation: deterministic, stateless parsers store line positions instead of events |
| `parallel_safe` | One instance may parse several inputs concurrently | `parse_async_iter` with `max_concurrency` above 1 |
| `partitionable`, `partition_framing` | A document may be split, for example by `"line"`, and its chunks parsed independently | `LinePartitioner` |
| `stateful` | Results depend on earlier inputs | Aggregation: stateful parsers retain their events |
| `requires_order` | Inputs must be parsed in order | Cannot be combined with `parallel_safe` |
| `incremental` | The parser handles inputs one at a time from a stream | Informational |
| `aggregatable` | Events may be aggregated by the package | Informational |

Unsafe combinations are rejected when the capabilities are created: a
partitionable parser must be deterministic, parallel-safe, stateless and
order-independent and must declare its framing, and a stateful or
order-dependent parser cannot be parallel-safe.

## Write a parser class

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
        return ParserCapabilities(
            deterministic=True, parallel_safe=True, aggregatable=True
        )

    async def parse(
        self, source: object, context: ParseContext | None = None
    ) -> ParseResult:
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
line positions. Aggregation and serialization are managed by the package:
defining `aggregator`, `aggregate`, `merge_aggregates`, `serialize` or
`deserialize` in a subclass raises `TypeError` when the class is created.

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

## Register and discover parsers

A `ParserRegistry` maps names to parser instances. There is no global
registry: create one per application or component. `register`, `get`,
`metadata`, `names` and `unregister` are thread-safe.

Packages can publish parsers as plugins through the `parsefabric.parsers`
entry-point group. Each entry point must reference a callable that takes no
arguments and returns a parser, such as a parser class:

```toml
[project.entry-points."parsefabric.parsers"]
access-log = "acme_parsers.access:AccessLogParser"
```

`ParserRegistry.discover()` loads every installed entry point and registers
the parsers it returns. Discovery is atomic: if any entry point fails, nothing
is registered. Loading an entry point imports and runs installed code, so
only install packages you trust.
