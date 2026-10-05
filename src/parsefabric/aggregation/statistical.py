"""Lossy statistical aggregation: counts and time ranges per group."""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Sequence
from typing import override

from parsefabric._json import dumps
from parsefabric.aggregation.base import Aggregate, Aggregator, CountAggregate
from parsefabric.models import JSONValue, ParsedEvent


def _group_identity(
    event_type: str, attributes: dict[str, JSONValue]
) -> tuple[str, str]:
    # Sorted JSON keeps booleans distinct from the numbers 0 and 1.
    return event_type, dumps(attributes, sort_keys=True)


class EventAccumulator:
    """Incremental state for counting a large event stream in bounded memory.

    Only one `CountAggregate` per distinct
    group is kept. Create it with `EventAggregator.accumulator`.

    Args:
        aggregator: The aggregator whose grouping this state follows.
    """

    def __init__(self, aggregator: EventAggregator) -> None:
        self._aggregator = aggregator
        self._groups: dict[tuple[str, str], CountAggregate] = {}

    def _add(self, partial: CountAggregate) -> None:
        key = _group_identity(partial.event_type, partial.key_attributes)
        current = self._groups.get(key)
        self._groups[key] = partial if current is None else current.merge(partial)

    def add(self, events: Iterable[ParsedEvent]) -> None:
        """Count events into their groups.

        Args:
            events: Events to count.
        """
        for event in events:
            self._add(
                CountAggregate(
                    event_type=event.event_type,
                    count=1,
                    first_seen=event.timestamp,
                    last_seen=event.timestamp,
                    key_attributes={
                        key: event.attributes.get(key)
                        for key in self._aggregator.group_by
                    },
                )
            )

    def merge(self, partials: Iterable[Aggregate]) -> None:
        """Merge partial summaries into the accumulated groups.

        Args:
            partials: Count aggregates produced with the same grouping.

        Raises:
            TypeError: If a partial is not a ``CountAggregate``.
        """
        for partial in partials:
            if not isinstance(partial, CountAggregate):
                raise TypeError("partials must be CountAggregate instances")
            self._add(partial)

    def result(self) -> tuple[CountAggregate, ...]:
        """Return the accumulated summaries in a deterministic order."""
        return tuple(self._groups[key] for key in sorted(self._groups))


class EventAggregator(Aggregator):
    """Count events by event type and selected attribute values.

    A statistical, lossy aggregator: it keeps counts and time ranges only, so
    it cannot materialize events. Merging partial results is associative and
    commutative, which suits partitioned or distributed counting. Parsers use
    the lossless `EvidenceAggregator`; use
    this aggregator directly for metrics.

    Args:
        group_by: Attribute names whose values, with the event type, identify
            a group. A missing attribute groups as ``None``.

    Raises:
        ValueError: If a name is empty, not a string, or repeated.
    """

    def __init__(self, *, group_by: Sequence[str] = ()) -> None:
        names = tuple(group_by)
        if any(not isinstance(name, str) or not name for name in names) or len(
            set(names)
        ) != len(names):
            raise ValueError("group_by names must be unique non-empty strings")
        self._group_by = names

    @property
    def group_by(self) -> tuple[str, ...]:
        """Attribute names that identify a group."""
        return self._group_by

    def accumulator(self) -> EventAccumulator:
        """Create independent incremental state that uses this grouping."""
        return EventAccumulator(self)

    @override
    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[CountAggregate, ...]:
        """Count events into one ``CountAggregate`` per group.

        Args:
            events: Events in any order.

        Returns:
            Summaries in a deterministic order.
        """
        accumulator = self.accumulator()
        if isinstance(events, AsyncIterable):
            async for event in events:
                accumulator.add((event,))
        else:
            accumulator.add(events)
        return accumulator.result()

    @override
    async def merge(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[CountAggregate, ...]:
        """Merge partial summaries, as produced for separate chunks of events.

        Args:
            partials: Count aggregates produced with the same grouping.

        Returns:
            Summaries equal to aggregating all the events at once.

        Raises:
            TypeError: If a partial is not a ``CountAggregate``.
        """
        accumulator = self.accumulator()
        if isinstance(partials, AsyncIterable):
            async for partial in partials:
                accumulator.merge((partial,))
        else:
            accumulator.merge(partials)
        return accumulator.result()
