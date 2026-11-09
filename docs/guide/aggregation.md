# Aggregation and storage

Operational text is repetitive: an incident can log the same timeout
thousands of times. Aggregation groups repeated events into compact evidence
without losing any of them, so you can store, transmit or summarize far less
data and still rebuild every original event exactly.

<figure class="diagram" markdown="span">
  ![Events of one source become one EvidenceAggregate per event type and parser, grouped by pattern and severity into one entry per distinct message, with a SHA-256 checksum over every canonical event; deterministic, stateless parsers store only line positions while other parsers store their events; materialize rebuilds the aggregates and compares them.](../assets/diagrams/aggregation.png){ width="776" }
  <figcaption>How events become lossless, checksummed aggregates.</figcaption>
</figure>

## Aggregate events

`ParseEngine.aggregate(parser, events)` (or `parser.aggregate(events)`)
aggregates the events of **one source document**, in source order, with the
parser's aggregator, a lossless `EvidenceAggregator` unless the parser
[chooses another](../extending/aggregators.md):

```python
--8<--
examples/aggregation.py
--8<--
```

Output:

```text
--8<-- "examples/expected/aggregation.txt"
```

## What an aggregate contains

| Level | Type | Holds |
| --- | --- | --- |
| Aggregate | `EvidenceAggregate` | One event type from one parser in one source: `count`, `first_seen` and `last_seen` timestamps, parser identity and an `events_sha256` checksum |
| Group | `EvidenceGroup` | Entries that share a pattern and a severity |
| Entry | `EvidenceEntry` | Every event of the group with one message: the `message`, the number of `occurrences` and the line `positions` |

A message is stored once however often it recurs, and its `positions` list
every line it occurs on, in source order. In the output above, the timeouts
on lines 4, 5 and 9 are one entry.

An entry's `message` is the event's string `message` attribute, or all of its
attributes when there is no message, so the aggregate states what happened
on its own. The `events_sha256` checksum covers the canonical form of every
event, including exact byte offsets.

## Positions or retained events

How much an aggregate stores depends on the parser's
[capabilities](custom-parsers.md#capabilities):

- **Deterministic, stateless parsers** produce the same events from the same
  input every time, so their aggregates store only line positions. To
  materialize them, you supply the exact source and parse context again.
- **All other parsers**, such as `SemanticParser` subclasses, may not
  reproduce their events, so their aggregates retain every event, with its
  position in the stream. Materializing them needs no source.

## Store aggregates

`await engine.serialize(aggregates)` encodes aggregates with the engine's
[`AggregateCodec`](../extending/codecs.md). The default `EvidenceCodec` writes the versioned
`parsefabric.aggregates/1` JSON format (pass `indent=2` for human reading),
and `await engine.deserialize(text)` decodes and validates it:

```json
{
  "format": "parsefabric.aggregates/1",
  "aggregates": [
    {
      "event_type": "timeout",
      "count": 3,
      "parser_name": "application-log",
      "parser_version": "1",
      "source_id": "db.log",
      "groups": [
        {
          "pattern": "timeout",
          "severity": "ERROR",
          "evidence": [
            {"message": "db timeout", "occurrences": 3, "positions": [1, 2, 4]}
          ]
        }
      ],
      "events_sha256": "6a952e3656d7ba441bede628f13b3d4b00bdd8a2672d2f9de7ce9905934598e4"
    }
  ]
}
```

Decoding is strict. Unknown or missing fields, duplicate keys, non-finite
numbers, inconsistent counts and invalid UTF-8 raise `SerializationError`,
so a stored document is either fully valid or rejected.

## Rebuild the events

`ParseEngine.materialize(parser, source, aggregates, context)` rebuilds the
original events and verifies them: it aggregates the candidate events again
and requires an exact match with the stored aggregates, checksums included.
For reproducible parsers the candidates come from parsing `source` with
`context`; pass the exact source, parser version and context that produced
the aggregates. For parsers that retain events, pass `None` as the source.
The order of the aggregates does not matter.

A mismatch raises `IntegrityError`, so materialized events are either exactly
the originals or not returned at all.

## Combine documents

Aggregate each complete source document once. `merge_aggregates` combines
aggregates of **different** documents; aggregates that describe the same
source, event type and parser raise `CapabilityError`, because a checksummed
document cannot be split and merged. To aggregate a document that you parsed
in partitions, re-base the partition events to document lines and aggregate
them together, as in [Streaming and execution](execution.md#partition-large-documents).

## Count events

When you need metrics rather than evidence, `EventAggregator` counts events by
event type and selected attributes. It is lossy, keeping only counts and
first and last timestamps as `CountAggregate` values, and its merge is
associative and commutative, which suits distributed counting:

```python
import asyncio

from parsefabric import ParseEngine
from parsefabric.aggregation import EventAggregator
from parsefabric.builtins import ApplicationLogParser


async def main() -> None:
    result = await ParseEngine().parse(
        ApplicationLogParser(),
        "db timeout\ndb timeout\nservice down\ndb timeout\n",
    )
    counts = await EventAggregator(group_by=("message",)).aggregate(result.events)
    for count in counts:
        print(count.event_type, count.key_attributes, count.count)


asyncio.run(main())
```

Output:

```text
service_down {'message': 'service down'} 1
timeout {'message': 'db timeout'} 3
```

For unbounded streams, `EventAggregator.accumulator()` returns an
`EventAccumulator` that keeps one count per group in bounded memory.

## Measure the savings

`await measure_compression(source, output)` compares sizes in bytes and in
tokens, which helps when aggregates feed a language model.
`CompressionMetrics` reports `input_bytes`, `output_bytes`, `bytes_saved`,
`reduction_percent` and the same figures for tokens. The default
`ApproximateTokenizer` counts one token per four UTF-8 bytes; to count with
your model's tokenizer, pass a [`Tokenizer`](../extending/tokenizers.md) as
`tokenizer`.
