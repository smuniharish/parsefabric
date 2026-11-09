# Aggregators

An aggregator turns the events of one source document into aggregates and
merges aggregates of different documents. Every parser has one: the default
`EvidenceAggregator` is lossless, and `EventAggregator` counts events. Write
your own when you need another summary, such as counts per severity or a
sketch for approximate distinct counts.

Subclass `Aggregator[YourAggregate]` and implement:

| Member | Contract |
| --- | --- |
| `async aggregate(events)` | Aggregate the events of one document, given as an iterable or an async iterable, and return a tuple |
| `async merge(partials)` | Combine aggregates, from an iterable or an async iterable; merging a complete set returns it unchanged |
| `lossless` | `True` only if `materialize` rebuilds every original event; defaults to `False` |
| `requires_source` | `True` if `materialize` needs the events of a fresh parse; defaults to `False` |
| `async materialize(aggregates, events)` | Rebuild the original events; lossy aggregators keep the default, which raises `CapabilityError` |

Aggregates are `Aggregate` subclasses: frozen dataclasses with an
`event_type`, a positive `count` and an optional time range. Use
`CountAggregate`, `EvidenceAggregate`, or your own subclass with a fixed set
of JSON fields.

Give a parser your aggregator by overriding `build_aggregator`, and
parameterize the parser with the aggregate type so that type checkers know
what `aggregate` returns. The parser builds the aggregator once and reuses
it, so keep aggregators free of per-run state:

```python
import asyncio
from collections.abc import AsyncIterable, Iterable

from parsefabric import ParseEngine, ParsedEvent
from parsefabric.aggregation import Aggregate, Aggregator, CountAggregate
from parsefabric.parser import DeterministicParser
from parsefabric.patterns import RegexPattern
from parsefabric.testing import check_aggregator


async def collect[T](items: Iterable[T] | AsyncIterable[T]) -> list[T]:
    if isinstance(items, AsyncIterable):
        return [item async for item in items]
    return list(items)


class SeverityAggregator(Aggregator[CountAggregate]):
    """Count events per severity. Lossy; merges across documents."""

    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[CountAggregate, ...]:
        counts: dict[str, int] = {}
        for event in await collect(events):
            severity = event.severity or "NONE"
            counts[severity] = counts.get(severity, 0) + 1
        return tuple(
            CountAggregate("severity", count, None, None, {"severity": severity})
            for severity, count in sorted(counts.items())
        )

    async def merge(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[CountAggregate, ...]:
        merged: dict[str, CountAggregate] = {}
        for partial in await collect(partials):
            if not isinstance(partial, CountAggregate):
                raise TypeError("SeverityAggregator merges CountAggregate values")
            key = str(partial.key_attributes["severity"])
            merged[key] = merged[key].merge(partial) if key in merged else partial
        return tuple(merged[key] for key in sorted(merged))


class SeverityParser(DeterministicParser[CountAggregate]):
    def build_aggregator(self) -> Aggregator[CountAggregate]:
        return SeverityAggregator()


async def main() -> None:
    parser = SeverityParser(
        [
            RegexPattern("error", r"^ERROR (?P<message>.+)", severity="ERROR"),
            RegexPattern("warning", r"^WARN (?P<message>.+)", severity="WARNING"),
        ],
        name="levels",
    )
    engine = ParseEngine()
    first = await engine.parse(parser, "ERROR disk full\nWARN slow\nERROR disk full\n")
    second = await engine.parse(parser, "WARN slow\n")
    await check_aggregator(parser.aggregator, first.events)

    partials = [
        *await engine.aggregate(parser, first.events),
        *await engine.aggregate(parser, second.events),
    ]
    for total in await engine.merge_aggregates(parser, partials):
        print(total.key_attributes["severity"], total.count)


asyncio.run(main())
```

```text
ERROR 2
WARNING 2
```

`check_aggregator(aggregator, events)` checks that aggregating a list and an
async stream agree, that merging a complete set returns it unchanged, and,
for a lossless aggregator, that `materialize` rebuilds exactly the events.

The engine refuses to `materialize` with an aggregator that is not
`lossless`, and an `AggregateCodec` stores only the aggregate types it
supports: `EvidenceCodec` stores `EvidenceAggregate`. To store your own
aggregates, write a [codec](codecs.md) for them.
