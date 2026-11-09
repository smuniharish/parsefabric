# Aggregation, storage and rebuilding

Read this when events are stored, sent to a model, or rebuilt later. The full
guide is
[Aggregation and storage](https://parsefabric.readthedocs.io/en/latest/guide/aggregation/).

## The round trip

<!-- docs-test: skip -->
```python
engine = ParseEngine()
context = ParseContext(source_id="checkout.log")
result = await engine.parse(parser, source, context)

aggregates = await engine.aggregate(parser, result.events)  # one document
stored = await engine.serialize(aggregates)  # str; indent=2 to read
loaded = await engine.deserialize(stored)  # strict validation
events = await engine.materialize(parser, source, loaded, context)
assert events == result.events
```

- `aggregate` takes the events of **one source document**, in source order.
- `merge_aggregates(parser, partials)` combines aggregates of **different**
  documents. Aggregates of the same source, event type and parser raise
  `CapabilityError`: a checksummed document cannot be split and merged.
- `serialize` uses the engine's `AggregateCodec`; the default `EvidenceCodec`
  writes the versioned `parsefabric.aggregates/1` JSON format. Pass
  `ParseEngine(codec=...)` to use another codec.
- `deserialize` rejects unknown or missing fields, duplicate keys, non-finite
  numbers, inconsistent counts and invalid UTF-8 with `SerializationError`.
- `materialize` parses again, aggregates again, and requires an exact match,
  checksums included. A mismatch raises `IntegrityError`; the events are
  either exactly the originals or not returned.

## What is stored

| Level | Type | Holds |
| --- | --- | --- |
| Aggregate | `EvidenceAggregate` | One event type from one parser in one source: `count`, `first_seen`, `last_seen`, parser identity and `events_sha256` |
| Group | `EvidenceGroup` | Entries that share a pattern and a severity |
| Entry | `EvidenceEntry` | Every event of the group with one message: `message`, `occurrences` and line `positions` |

A message is stored once however often it recurs, and `positions` lists every
line it occurs on, in source order. That is why a bursty log shrinks by about
90%.

## Positions or retained events

- **Deterministic, stateless parsers** reproduce their events, so aggregates
  store only positions. `materialize` needs the exact source, context and
  parser version.
- **Other parsers**, such as `SemanticParser` subclasses, retain every event
  with its stream position. Pass `None` as the source to `materialize`.

Bump a parser's `version` whenever its output for the same input changes.
Stored aggregates of the old version then fail loudly instead of rebuilding
different events.

## Counting instead of evidence

When only metrics are needed, `EventAggregator(group_by=("message",))` from
`parsefabric.aggregation` counts events into `CountAggregate` values. It is
lossy, so it cannot materialize. `EventAggregator.accumulator()` counts an
unbounded stream in bounded memory.

## Measuring the reduction

<!-- docs-test: skip -->
```python
from parsefabric import measure_compression

metrics = await measure_compression(source, stored)
print(metrics.reduction_percent)
```

`CompressionMetrics` reports bytes and tokens. The default
`ApproximateTokenizer` counts one token per four UTF-8 bytes; pass
`tokenizer=` to count with the model's tokenizer. Verify losslessness with
`materialize` before you rely on the reduction.
