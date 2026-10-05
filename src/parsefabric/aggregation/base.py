"""Aggregate models and the aggregator contract.

Aggregates are typed Python objects with a fixed, package-owned JSON form.
`Aggregate.to_dict` and `Aggregate.from_dict` convert one concrete
aggregate type; there is no registry of aggregate kinds because every parser
produces the same `EvidenceAggregate` and
serializes it through the package-managed `Parser.serialize`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Self, override

from parsefabric._json import (
    STRUCTURE_DEPTH,
    check_text,
    copy_json,
    dumps,
    require_object,
)
from parsefabric.errors import CapabilityError
from parsefabric.models import JSONValue, ParsedEvent

_TIME_FIELDS = frozenset(("first_seen", "last_seen"))


def _time(fields: dict[str, Any], key: str) -> datetime | None:
    if key not in fields:
        return None
    value = fields[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be an ISO 8601 string")
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class Aggregate:
    """Fields shared by every aggregate: what was summarized, how often, when.

    Attributes:
        event_type: Event type the aggregate summarizes.
        count: Number of events, at least one.
        first_seen: Earliest event timestamp, if any event had one.
        last_seen: Latest event timestamp, if any event had one.
    """

    FIELDS: ClassVar[tuple[str, ...]] = ()
    """JSON fields of the concrete type beyond the common fields."""

    event_type: str
    count: int
    first_seen: datetime | None
    last_seen: datetime | None

    def __post_init__(self) -> None:
        if type(self.count) is not int or self.count < 1:
            raise ValueError("aggregate count must be a positive integer")
        if not isinstance(self.event_type, str) or not self.event_type:
            raise ValueError("aggregate event_type must not be empty")
        check_text(self.event_type, "aggregate event_type")
        if any(
            timestamp is not None
            and (not isinstance(timestamp, datetime) or timestamp.utcoffset() is None)
            for timestamp in (self.first_seen, self.last_seen)
        ):
            raise ValueError("aggregate timestamps must be timezone-aware")
        if (
            self.first_seen is not None
            and self.last_seen is not None
            and self.first_seen > self.last_seen
        ):
            raise ValueError("first_seen must not be later than last_seen")

    def to_dict(self) -> dict[str, JSONValue]:
        """Return an independent copy of the canonical JSON representation.

        ``first_seen`` and ``last_seen`` are omitted when unknown.
        """
        return copy_json(self._to_wire(), "aggregate", max_depth=STRUCTURE_DEPTH)

    def _to_wire(self) -> dict[str, JSONValue]:
        """Return the representation sharing nested values, for encoding."""
        data: dict[str, JSONValue] = {
            "event_type": self.event_type,
            "count": self.count,
        }
        if self.first_seen is not None:
            data["first_seen"] = self.first_seen.isoformat()
        if self.last_seen is not None:
            data["last_seen"] = self.last_seen.isoformat()
        return data | self._fields_to_wire()

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Rebuild an aggregate of this type from `to_dict` output.

        Args:
            data: A decoded JSON object.

        Returns:
            The validated aggregate.

        Raises:
            ValueError: If ``data`` does not have exactly the fields of this
                aggregate type or a field is invalid.
        """
        fields = require_object(
            data,
            cls.__name__,
            frozenset(("event_type", "count", *cls.FIELDS)),
            _TIME_FIELDS,
        )
        return cls(
            event_type=fields["event_type"],
            count=fields["count"],
            first_seen=_time(fields, "first_seen"),
            last_seen=_time(fields, "last_seen"),
            **cls._fields_from_dict(fields),
        )

    def _fields_to_wire(self) -> dict[str, JSONValue]:
        """Return the type-specific fields; overridden by concrete types."""
        return {}

    @classmethod
    def _fields_from_dict(cls, fields: dict[str, Any]) -> dict[str, Any]:
        """Return constructor arguments for the type-specific fields."""
        return {}


def _time_range(
    *values: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    present = [value for value in values if value is not None]
    return (min(present), max(present)) if present else (None, None)


@dataclass(frozen=True, slots=True)
class CountAggregate(Aggregate):
    """Lossy statistical summary: a count and time range per attribute group.

    Attributes:
        key_attributes: Values of the grouping attributes; missing attributes
            are ``None``.
    """

    FIELDS: ClassVar[tuple[str, ...]] = ("key_attributes",)

    key_attributes: dict[str, JSONValue]

    @override
    def __post_init__(self) -> None:
        Aggregate.__post_init__(self)
        if not isinstance(self.key_attributes, dict):
            raise ValueError("aggregate key attributes must be a JSON object")
        object.__setattr__(
            self,
            "key_attributes",
            copy_json(self.key_attributes, "aggregate key attributes"),
        )

    @override
    def _fields_to_wire(self) -> dict[str, JSONValue]:
        return {"key_attributes": self.key_attributes}

    @classmethod
    @override
    def _fields_from_dict(cls, fields: dict[str, Any]) -> dict[str, Any]:
        return {"key_attributes": fields["key_attributes"]}

    def merge(self, other: CountAggregate) -> CountAggregate:
        """Combine two partial summaries of the same group.

        Args:
            other: A summary with the same event type and key attributes.

        Returns:
            The combined summary.

        Raises:
            TypeError: If ``other`` is not a `CountAggregate`.
            ValueError: If the summaries belong to different groups.
        """
        if not isinstance(other, CountAggregate):
            raise TypeError("can only merge CountAggregate partials")
        if self.event_type != other.event_type or dumps(
            self.key_attributes, sort_keys=True
        ) != dumps(other.key_attributes, sort_keys=True):
            raise ValueError("cannot merge aggregates of different groups")
        first_seen, last_seen = _time_range(
            self.first_seen, self.last_seen, other.first_seen, other.last_seen
        )
        return CountAggregate(
            event_type=self.event_type,
            count=self.count + other.count,
            first_seen=first_seen,
            last_seen=last_seen,
            key_attributes=self.key_attributes,
        )


class Aggregator(ABC):
    """Aggregation strategy of a parser, with explicit merge behavior."""

    @property
    def lossless(self) -> bool:
        """Whether `materialize` can rebuild every original event."""
        return False

    @property
    def requires_source(self) -> bool:
        """Whether `materialize` needs the events of a fresh re-parse."""
        return False

    async def materialize(
        self,
        aggregates: Sequence[Aggregate],
        events: Sequence[ParsedEvent] | None = None,
    ) -> tuple[ParsedEvent, ...]:
        """Rebuild and verify the original events.

        Args:
            aggregates: Every aggregate of one source document.
            events: Events of a fresh parse, for aggregators that require
                the source.

        Returns:
            The verified original events.

        Raises:
            CapabilityError: Always, for lossy aggregators.
        """
        raise CapabilityError(
            f"{type(self).__name__} is a lossy aggregator and cannot materialize"
        )

    @abstractmethod
    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[Aggregate, ...]:
        """Create aggregates from an event stream.

        Args:
            events: Events to aggregate.

        Returns:
            The aggregates.
        """

    @abstractmethod
    async def merge(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[Aggregate, ...]:
        """Merge partial aggregates into deterministic output.

        Args:
            partials: Aggregates produced by this aggregator.

        Returns:
            The merged aggregates.
        """
