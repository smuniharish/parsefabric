"""Lossy statistical aggregation: counts and time ranges per group."""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Sequence
from typing import TYPE_CHECKING, override

from parsefabric._json import dumps
from parsefabric.aggregation.base import Aggregate, Aggregator, CountAggregate

if TYPE_CHECKING:
    from datetime import datetime

    from parsefabric.models import JSONValue, ParsedEvent


def _group_identity(event_type: str, attributes: dict[str, JSONValue]) -> tuple[str, str]:
    # Sorted JSON keeps booleans distinct from the numbers 0 and 1.
    return event_type, dumps(attributes, sort_keys=True)


class _Tally:
    """Mutable running count and time range of one group."""

    __slots__ = ("count", "event_type", "first_seen", "key_attributes", "last_seen")

    def __init__(self, event_type: str, key_attributes: dict[str, JSONValue]) -> None:
        self.event_type = event_type
        self.key_attributes = key_attributes
        self.count = 0
        self.first_seen: datetime | None = None
        self.last_seen: datetime | None = None

    def add(self, count: int, first_seen: datetime | None, last_seen: datetime | None) -> None:
        self.count += count
        if first_seen is not None and (self.first_seen is None or first_seen < self.first_seen):
            self.first_seen = first_seen
        if last_seen is not None and (self.last_seen is None or last_seen > self.last_seen):
            self.last_seen = last_seen

    def aggregate(self) -> CountAggregate:
        return CountAggregate(
            event_type=self.event_type,
            count=self.count,
            first_seen=self.first_seen,
            last_seen=self.last_seen,
            key_attributes=self.key_attributes,
        )


class EventAccumulator:
    """Incremental state for counting a large event stream in bounded memory.

    Only a running count and time range per distinct group is kept; the
    `CountAggregate` summaries are built by `result`. Create it with
    `EventAggregator.accumulator`.

    Args:
        aggregator: The aggregator whose grouping this state follows.
    """

    def __init__(self, aggregator: EventAggregator) -> None:
        self._group_by = aggregator.group_by
        self._groups: dict[tuple[str, str], _Tally] = {}

    def _tally(self, event_type: str, key_attributes: dict[str, JSONValue]) -> _Tally:
        key = _group_identity(event_type, key_attributes)
        tally = self._groups.get(key)
        if tally is None:
            tally = self._groups[key] = _Tally(event_type, key_attributes)
        return tally

    def add(self, events: Iterable[ParsedEvent]) -> None:
        """Count events into their groups.

        Args:
            events: Events to count.
        """
        group_by = self._group_by
        for event in events:
            attributes = event.attributes
            self._tally(event.event_type, {key: attributes.get(key) for key in group_by}).add(
                1, event.timestamp, event.timestamp
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
            self._tally(partial.event_type, partial.key_attributes).add(
                partial.count, partial.first_seen, partial.last_seen
            )

    def result(self) -> tuple[CountAggregate, ...]:
        """Return the accumulated summaries in a deterministic order."""
        return tuple(self._groups[key].aggregate() for key in sorted(self._groups))


class EventAggregator(Aggregator[CountAggregate]):
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
        if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(
            names
        ):
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
