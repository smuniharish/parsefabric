# Parsers, aggregators and codecs

Read this when writing a parser, an aggregator, or a codec for stored
aggregates. The full guides are
[Parsers](https://parsefabric.readthedocs.io/en/latest/extending/parsers/),
[Aggregators](https://parsefabric.readthedocs.io/en/latest/extending/aggregators/)
and [Codecs](https://parsefabric.readthedocs.io/en/latest/extending/codecs/).

## Choose a base class

| Base class | Use it for |
| --- | --- |
| `DeterministicParser(patterns, name=..., version=...)` | Line-by-line pattern matching; no subclass needed |
| `Parser` | Any other format, with the capabilities you can promise |
| `AsyncParser` | Parsing that awaits I/O, such as a service call |
| `SemanticParser` | Interpretation by a `LanguageModel` or other non-reproducible logic |

## Capabilities

`ParserCapabilities` tells the engine what it may do with the parser.

| Flag | Promise | Unlocks |
| --- | --- | --- |
| `deterministic` | Equal input and context give equal results | Aggregates store line positions; `materialize` re-parses |
| `parallel_safe` | One instance parses several inputs concurrently | `max_concurrency` and execution backends |
| `stateful`, `requires_order` | Results depend on earlier inputs | Nothing; excludes `parallel_safe` |
| `partitionable` with `partition_framing="line"` | Each line parses on its own | `LinePartitioner` |
| `aggregatable` | Events may be aggregated | `engine.aggregate` |

Wrong promises corrupt stored data: a parser that claims `deterministic` but
is not makes `materialize` raise `IntegrityError` or rebuild wrong events.

## Evidence

- Set `line_number` (one-based), `start_offset` and `end_offset` (UTF-8
  bytes, end exclusive) and `pattern_name` with
  `event.with_evidence(Evidence(...))`.
- Add `context.source_offset` to byte offsets, so partitions stay
  document-relative.
- The engine fills in `source_id`, `parser_name`, `parser_version` and
  `correlation_id`; leave them unset.
- Events must survive `dumps_result` and `loads_result`: attributes hold
  JSON values only.

## Versions

Stored aggregates are rebuilt by the parser with the same name and version.
Bump `version` whenever the events for the same input change, including a
new attribute or a different severity.

## Aggregators

- Subclass `Aggregator[YourAggregate]`; implement `async aggregate(events)`
  and `async merge(partials)`. Both accept iterables and async iterables.
- Merging a complete set of aggregates returns it unchanged.
- Set `lossless = True` only if `materialize` rebuilds every original event,
  and `requires_source = True` if it needs the events of a fresh parse.
- Aggregates are frozen `Aggregate` subclasses with JSON fields. Keep
  aggregators free of per-run state: a parser builds one and reuses it.
- Give a parser the aggregator by overriding `build_aggregator`.

## Codecs

- `AggregateCodec`: `format` is written into every document; `encode` is
  deterministic; `decode` accepts text or UTF-8 bytes and raises
  `SerializationError` for anything invalid, never a partial result.
- `JSONCodec`: `decode(text)` returns standard JSON values with exact
  integers, and raises `ValueError` for malformed documents.
- Pass an aggregate codec as `ParseEngine(codec=)` and a JSON codec as
  `JSONParser(codec=)`.
