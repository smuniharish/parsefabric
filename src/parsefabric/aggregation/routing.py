"""Delegate aggregation to the aggregators of the parsers that produced events."""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Mapping, Sequence
from typing import override

from parsefabric.aggregation.base import Aggregate, Aggregator
from parsefabric.errors import IntegrityError
from parsefabric.models import ParsedEvent


class RoutingAggregator(Aggregator):
    """Aggregate each event with the aggregator of the parser that produced it.

    Composite parsers such as
    `MixedContentParser` emit events from
    several parsers. Events whose ``evidence.parser_name`` appears in
    ``routes`` are aggregated by that aggregator; all others by ``default``.
    Each partition keeps its stream order, and outputs are ordered by first
    appearance.

    Args:
        default: Aggregator for events of parsers without a route.
        routes: Aggregator for each parser name.

    Raises:
        TypeError: If an aggregator or name has the wrong type.
    """

    def __init__(
        self, default: Aggregator, routes: Mapping[str, Aggregator] | None = None
    ) -> None:
        if not isinstance(default, Aggregator):
            raise TypeError("default must be an Aggregator")
        self._default = default
        self._routes = dict(routes or {})
        if any(
            not isinstance(name, str) or not isinstance(aggregator, Aggregator)
            for name, aggregator in self._routes.items()
        ):
            raise TypeError("routes must map parser names to Aggregator instances")

    @property
    def default(self) -> Aggregator:
        """Aggregator for events whose parser has no dedicated route."""
        return self._default

    @property
    def routes(self) -> Mapping[str, Aggregator]:
        """Copy of the parser-name to aggregator routing table."""
        return dict(self._routes)

    def _key(self, parser_name: str | None) -> str | None:
        return parser_name if parser_name in self._routes else None

    def _aggregator(self, key: str | None) -> Aggregator:
        return self._default if key is None else self._routes[key]

    def _children(self) -> tuple[Aggregator, ...]:
        return (self._default, *self._routes.values())

    @property
    @override
    def lossless(self) -> bool:
        return all(child.lossless for child in self._children())

    @property
    @override
    def requires_source(self) -> bool:
        return any(child.requires_source for child in self._children())

    @override
    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[Aggregate, ...]:
        partitions: dict[str | None, list[ParsedEvent]] = {}

        def add(event: ParsedEvent) -> None:
            if not isinstance(event, ParsedEvent):
                raise TypeError("events must be ParsedEvent instances")
            key = self._key(event.evidence.parser_name)
            partitions.setdefault(key, []).append(event)

        if isinstance(events, AsyncIterable):
            async for event in events:
                add(event)
        else:
            for event in events:
                add(event)
        results: list[Aggregate] = []
        for key, partition in partitions.items():
            results.extend(await self._aggregator(key).aggregate(partition))
        return tuple(results)

    def _aggregate_key(self, aggregate: Aggregate) -> str | None:
        parser_name = getattr(aggregate, "parser_name", None)
        return self._key(parser_name if isinstance(parser_name, str) else None)

    @override
    async def materialize(
        self,
        aggregates: Sequence[Aggregate],
        events: Sequence[ParsedEvent] | None = None,
    ) -> tuple[ParsedEvent, ...]:
        """Materialize each partition with its own aggregator, in source order."""
        grouped: dict[str | None, list[Aggregate]] = {}
        for aggregate in aggregates:
            grouped.setdefault(self._aggregate_key(aggregate), []).append(aggregate)
        given: dict[str | None, list[ParsedEvent]] = {}
        for event in events or ():
            given.setdefault(self._key(event.evidence.parser_name), []).append(event)
        partitions: list[tuple[ParsedEvent, ...]] = []
        from_source = True
        for key in dict.fromkeys((*grouped, *given)):
            aggregator = self._aggregator(key)
            if aggregator.requires_source and events is None:
                raise IntegrityError(
                    "a routed aggregator requires the events of a fresh re-parse"
                )
            partitions.append(
                await aggregator.materialize(
                    grouped.get(key, ()),
                    given.get(key, []) if aggregator.requires_source else None,
                )
            )
            from_source = from_source and aggregator.requires_source
        if events is not None and from_source:
            return tuple(events)
        rebuilt = [event for partition in partitions for event in partition]
        if len(partitions) <= 1:
            return tuple(rebuilt)
        if any(event.evidence.line_number is None for event in rebuilt):
            raise IntegrityError(
                "events from several parsers need line numbers to restore order"
            )
        return tuple(
            sorted(
                rebuilt,
                key=lambda event: (
                    event.evidence.line_number,
                    event.evidence.start_offset or 0,
                ),
            )
        )

    @override
    async def merge(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[Aggregate, ...]:
        grouped: dict[str | None, list[Aggregate]] = {}
        if isinstance(partials, AsyncIterable):
            async for item in partials:
                grouped.setdefault(self._aggregate_key(item), []).append(item)
        else:
            for item in partials:
                grouped.setdefault(self._aggregate_key(item), []).append(item)
        results: list[Aggregate] = []
        for key, items in grouped.items():
            results.extend(await self._aggregator(key).merge(items))
        return tuple(results)
