"""Lossless, grouped evidence aggregation.

Events of one source are grouped into one `EvidenceAggregate` per
``(event_type, parser_name)``, then into `EvidenceGroup` objects per
``(pattern, severity)``. Each `EvidenceEntry` stores a distinct message
once with its occurrence count and the 1-based source line ``positions`` of
its events. Reproducible parsers rebuild every event by re-parsing the source;
other parsers retain the events in the entries. Every aggregate carries a
SHA-256 over its complete canonical events, and
`EvidenceAggregator.materialize` rebuilds and verifies them exactly.

Every aggregate has one canonical JSON form (`Aggregate.to_dict`),
identical for every parser because the only parser-specific value, the entry
``message``, is itself JSON; `Parser.serialize` owns the envelope.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, override

from parsefabric._json import (
    canonical_dumps,
    check_text,
    copy_json,
    dumps,
    require_object,
)
from parsefabric.aggregation.base import Aggregate, Aggregator
from parsefabric.errors import CapabilityError, IntegrityError
from parsefabric.models import Evidence, JSONValue, ParsedEvent

type Position = int | None
type MessageFunction = Callable[[ParsedEvent], JSONValue]

_SHA256 = re.compile(r"[0-9a-f]{64}")


_GROUP_FIELDS = frozenset(("pattern", "severity", "evidence"))
_ENTRY_FIELDS = frozenset(("message", "occurrences", "positions"))
_RETAINED_FIELDS = frozenset(("events", "sequence"))


def canonical_event(event: ParsedEvent) -> str:
    """Return the canonical JSON text that event checksums are computed over.

    The text is compact UTF-8 JSON with sorted keys, so equal events always
    produce identical text.

    Args:
        event: Event to encode.

    Returns:
        The canonical text.
    """
    return canonical_dumps(event._to_wire())


def default_event_message(event: ParsedEvent) -> JSONValue:
    """Return the information an evidence entry carries for its events.

    The message is the event's string ``message`` attribute (a parser's
    compact statement of what happened, such as a log message); otherwise all
    of the event's attributes (for example a JSON value, a metric name and
    value, or unmatched text), so the aggregate itself says what occurred and
    positions only record where and in which order. ``None`` only for events
    without attributes.

    Args:
        event: Event to describe.

    Returns:
        The entry message.
    """
    message = event.attributes.get("message")
    if isinstance(message, str):
        return message
    return dict(event.attributes) or None


def _message_key(value: JSONValue) -> object:
    # Text messages compare as themselves; other values by their sorted JSON,
    # wrapped in a tuple so that they never equal a text message.
    if type(value) is str:
        return value
    try:
        return ("json", dumps(value, sort_keys=True))
    except (TypeError, ValueError) as error:
        raise TypeError("event messages must be JSON-compatible values") from error


def _is_position(value: object) -> bool:
    return value is None or (type(value) is int and value >= 1)


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    """One distinct message, or one consecutive run of it, and where it occurs.

    ``positions`` holds the 1-based source line of each occurrence in source
    order (the first line of a multi-line event), or ``None`` when the parser
    cannot locate it. Exact offsets are not stored: they are part of the
    checksummed events that ``materialize`` rebuilds and verifies. ``events``
    and their stream ``sequence`` positions are retained only for parsers
    whose events cannot be rebuilt by re-parsing the source.

    Attributes:
        message: JSON-compatible description shared by the occurrences.
        occurrences: Number of events represented.
        positions: Source line of each occurrence.
        events: Retained events, for non-reproducible parsers.
        sequence: Zero-based stream position of each retained event.
    """

    message: JSONValue
    occurrences: int
    positions: tuple[Position, ...]
    events: tuple[ParsedEvent, ...] = ()
    sequence: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", copy_json(self.message, "evidence message"))
        if type(self.occurrences) is not int or self.occurrences < 1:
            raise ValueError("occurrences must be a positive integer")
        if not isinstance(self.positions, tuple) or any(
            not _is_position(value) for value in self.positions
        ):
            raise ValueError("positions must be positive line numbers or None")
        if len(self.positions) != self.occurrences:
            raise ValueError("each occurrence needs exactly one position")
        known = [value for value in self.positions if value is not None]
        if known != sorted(known):
            raise ValueError("positions must be in source order")
        if not isinstance(self.events, tuple) or any(
            not isinstance(event, ParsedEvent) for event in self.events
        ):
            raise ValueError("retained events must be ParsedEvent instances")
        if self.events and len(self.events) != self.occurrences:
            raise ValueError("retained events must match occurrences")
        if (
            not isinstance(self.sequence, tuple)
            or len(self.sequence) != len(self.events)
            or any(type(value) is not int or value < 0 for value in self.sequence)
        ):
            raise ValueError("each retained event needs a stream position")


@dataclass(frozen=True, slots=True)
class EvidenceGroup:
    """Entries sharing one pattern and severity, such as one log level.

    Attributes:
        pattern: Pattern or route that produced the events, if any.
        severity: Severity of the events, if any.
        evidence: Entries in source order of their first occurrence.
    """

    pattern: str | None
    severity: str | None
    evidence: tuple[EvidenceEntry, ...]

    def __post_init__(self) -> None:
        for value in (self.pattern, self.severity):
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("pattern and severity must be strings or None")
                check_text(value, "pattern and severity")
        if (
            not isinstance(self.evidence, tuple)
            or not self.evidence
            or any(not isinstance(entry, EvidenceEntry) for entry in self.evidence)
        ):
            raise ValueError("an evidence group needs EvidenceEntry items")

    @property
    def occurrences(self) -> int:
        """Total events represented by this group."""
        return sum(entry.occurrences for entry in self.evidence)


@dataclass(frozen=True, slots=True)
class EvidenceAggregate(Aggregate):
    """Lossless summary of one event type from one parser in one source.

    Attributes:
        source_id: Source document of the events.
        parser_name: Parser that produced the events.
        parser_version: Version of that parser.
        groups: Entries grouped by pattern and severity.
        events_sha256: SHA-256 over the canonical text of every event, in
            stream order, each followed by a newline.
    """

    FIELDS: ClassVar[tuple[str, ...]] = (
        "parser_name",
        "parser_version",
        "source_id",
        "groups",
        "events_sha256",
    )

    source_id: str | None
    parser_name: str | None
    parser_version: str | None
    groups: tuple[EvidenceGroup, ...]
    events_sha256: str

    @override
    def __post_init__(self) -> None:
        Aggregate.__post_init__(self)
        for value in (self.source_id, self.parser_name, self.parser_version):
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(
                        "source, parser name, and version must be str or None"
                    )
                check_text(value, "source, parser name, and version")
        if (
            not isinstance(self.groups, tuple)
            or not self.groups
            or any(not isinstance(group, EvidenceGroup) for group in self.groups)
        ):
            raise ValueError("an evidence aggregate needs EvidenceGroup items")
        entries = [entry for group in self.groups for entry in group.evidence]
        if sum(entry.occurrences for entry in entries) != self.count:
            raise ValueError("occurrences do not add up to the aggregate count")
        if len({bool(entry.events) for entry in entries}) > 1:
            raise ValueError("either every entry or none retains its events")
        if not isinstance(self.events_sha256, str) or not _SHA256.fullmatch(
            self.events_sha256
        ):
            raise ValueError("events_sha256 must be a lowercase SHA-256 hex digest")

    @property
    def retains_events(self) -> bool:
        """Whether the entries carry the events themselves."""
        return bool(self.groups[0].evidence[0].events)

    @override
    def _fields_to_wire(self) -> dict[str, JSONValue]:
        return {
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "source_id": self.source_id,
            "groups": [
                {
                    "pattern": group.pattern,
                    "severity": group.severity,
                    "evidence": [_entry_to_wire(entry) for entry in group.evidence],
                }
                for group in self.groups
            ],
            "events_sha256": self.events_sha256,
        }

    @classmethod
    @override
    def _fields_from_dict(cls, fields: dict[str, Any]) -> dict[str, Any]:
        groups = fields["groups"]
        if not isinstance(groups, list):
            raise ValueError("groups must be a list")
        return {
            "source_id": fields["source_id"],
            "parser_name": fields["parser_name"],
            "parser_version": fields["parser_version"],
            "groups": tuple(_group_from_dict(group) for group in groups),
            "events_sha256": fields["events_sha256"],
        }


def _entry_to_wire(entry: EvidenceEntry) -> dict[str, JSONValue]:
    data: dict[str, JSONValue] = {
        "message": entry.message,
        "occurrences": entry.occurrences,
        "positions": list(entry.positions),
    }
    if entry.events:
        data["events"] = [event._to_wire() for event in entry.events]
        data["sequence"] = list(entry.sequence)
    return data


def _list(fields: dict[str, Any], key: str) -> list[Any]:
    value = fields[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _group_from_dict(data: object) -> EvidenceGroup:
    fields = require_object(data, "evidence group", _GROUP_FIELDS)
    return EvidenceGroup(
        pattern=fields["pattern"],
        severity=fields["severity"],
        evidence=tuple(_entry_from_dict(entry) for entry in _list(fields, "evidence")),
    )


def _entry_from_dict(data: object) -> EvidenceEntry:
    fields = require_object(data, "evidence entry", _ENTRY_FIELDS, _RETAINED_FIELDS)
    if ("events" in fields) != ("sequence" in fields):
        raise ValueError("retained events and their sequence must appear together")
    events: tuple[ParsedEvent, ...] = ()
    sequence: tuple[int, ...] = ()
    if "events" in fields:
        retained = _list(fields, "events")
        if not retained:
            raise ValueError("retained events must not be empty")
        events = tuple(ParsedEvent.from_dict(event) for event in retained)
        sequence = tuple(_list(fields, "sequence"))
    return EvidenceEntry(
        message=fields["message"],
        occurrences=fields["occurrences"],
        positions=tuple(_list(fields, "positions")),
        events=events,
        sequence=sequence,
    )


@dataclass
class _Entry:
    message: JSONValue
    positions: list[Position] = field(default_factory=list)
    occurrences: int = 0
    events: list[ParsedEvent] = field(default_factory=list)
    sequence: list[int] = field(default_factory=list)


@dataclass
class _Document:
    event_type: str
    parser_name: str | None
    parser_version: str | None
    groups: dict[tuple[str | None, str | None], list[_Entry]] = field(
        default_factory=dict
    )
    digest: Any = field(default_factory=hashlib.sha256)
    count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None


def _adjacent(previous: Evidence, current: Evidence) -> bool:
    """Whether ``current`` directly follows ``previous`` in the source.

    Events whose byte spans abut are adjacent. Otherwise events on the same
    or the next line are adjacent, so any skipped line, blank or not, starts
    a new run regardless of the line ending. Events without comparable
    locations follow each other in stream order.
    """
    has_offsets = previous.end_offset is not None and current.start_offset is not None
    if has_offsets and current.start_offset == previous.end_offset:
        return True
    if previous.line_number is not None and current.line_number is not None:
        return 0 <= current.line_number - previous.line_number <= 1
    return not has_offsets


def _identity(aggregate: EvidenceAggregate) -> tuple[str, str | None]:
    return aggregate.event_type, aggregate.parser_name


class EvidenceAggregator(Aggregator):
    """Group events by type, parser, pattern, severity and message losslessly.

    Each source yields one aggregate per ``(event_type, parser_name)``. Only
    identical events that directly follow each other in the source form one
    entry listing the line position of each event in the run, so a
    recurrence after any other event or skipped source line starts a new
    entry and the source order is kept.

    Args:
        reproducible: Whether the owning parser rebuilds identical events from
            the same source and context. Reproducible aggregates store only
            positions; otherwise every event is retained.
        message: Function deriving an entry's message from an event. Defaults
            to `default_event_message`.
    """

    def __init__(
        self,
        *,
        reproducible: bool = False,
        message: MessageFunction | None = None,
    ) -> None:
        if not isinstance(reproducible, bool):
            raise TypeError("reproducible must be bool")
        if message is not None and not callable(message):
            raise TypeError("message must be callable")
        self._reproducible = reproducible
        self._message = message or default_event_message

    @property
    def reproducible(self) -> bool:
        """Whether the owning parser rebuilds identical events on re-parse."""
        return self._reproducible

    @property
    @override
    def lossless(self) -> bool:
        return True

    @property
    @override
    def requires_source(self) -> bool:
        return self.reproducible

    @override
    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[EvidenceAggregate, ...]:
        """Aggregate the events of one source document.

        Args:
            events: Events of a single source, in source order.

        Returns:
            One aggregate per event type and parser, in order of first
            appearance.

        Raises:
            TypeError: If an item is not a `ParsedEvent` or a message
                is not JSON-compatible.
            ValueError: If the events mix sources, go backwards in the source,
                or mix versions of one parser.
        """
        documents: dict[tuple[str, str | None], _Document] = {}
        versions: dict[str, str | None] = {}
        source_id: str | None = None
        last_line: int | None = None
        # Run key and evidence of the previous event.
        previous: (
            tuple[
                tuple[tuple[str, str | None], tuple[str | None, str | None], object],
                Evidence,
            ]
            | None
        ) = None
        count = 0

        def add(event: ParsedEvent) -> None:
            nonlocal source_id, last_line, previous, count
            if not isinstance(event, ParsedEvent):
                raise TypeError("events must be ParsedEvent instances")
            evidence = event.evidence
            if count and evidence.source_id != source_id:
                raise ValueError("aggregate each source document separately")
            line = evidence.line_number
            if last_line is not None and line is not None and line < last_line:
                raise ValueError("events must be in source order")
            if evidence.parser_name is not None:
                known = versions.setdefault(
                    evidence.parser_name, evidence.parser_version
                )
                if known != evidence.parser_version:
                    raise ValueError(
                        f"parser {evidence.parser_name!r} appears with "
                        "different versions in one document"
                    )
            source_id = evidence.source_id
            last_line = line if line is not None else last_line
            doc_key = (event.event_type, evidence.parser_name)
            document = documents.get(doc_key)
            if document is None:
                document = documents[doc_key] = _Document(
                    event.event_type, evidence.parser_name, evidence.parser_version
                )
            if document.parser_version != evidence.parser_version:
                raise ValueError("events of one parser must share a version")
            group_key = (evidence.pattern_name, event.severity)
            message = self._message(event)
            message_key = _message_key(message)
            entries = document.groups.setdefault(group_key, [])
            current = (doc_key, group_key, message_key)
            if (
                previous is not None
                and previous[0] == current
                and _adjacent(previous[1], evidence)
            ):
                entry = entries[-1]
            else:
                entry = _Entry(message)
                entries.append(entry)
            entry.positions.append(line)
            entry.occurrences += 1
            if not self.reproducible:
                entry.events.append(event)
                entry.sequence.append(count)
            document.digest.update(canonical_event(event).encode("utf-8") + b"\n")
            document.count += 1
            if event.timestamp is not None:
                document.first_seen = (
                    event.timestamp
                    if document.first_seen is None
                    else min(document.first_seen, event.timestamp)
                )
                document.last_seen = (
                    event.timestamp
                    if document.last_seen is None
                    else max(document.last_seen, event.timestamp)
                )
            previous = (current, evidence)
            count += 1

        if isinstance(events, AsyncIterable):
            async for event in events:
                add(event)
        else:
            for event in events:
                add(event)
        return tuple(
            self._document_aggregate(document, source_id)
            for document in documents.values()
        )

    def _document_aggregate(
        self, document: _Document, source_id: str | None
    ) -> EvidenceAggregate:
        return EvidenceAggregate(
            event_type=document.event_type,
            count=document.count,
            first_seen=document.first_seen,
            last_seen=document.last_seen,
            source_id=source_id,
            parser_name=document.parser_name,
            parser_version=document.parser_version,
            groups=tuple(
                EvidenceGroup(
                    pattern,
                    severity,
                    tuple(
                        EvidenceEntry(
                            entry.message,
                            entry.occurrences,
                            tuple(entry.positions),
                            tuple(entry.events),
                            tuple(entry.sequence),
                        )
                        for entry in entries
                    ),
                )
                for (pattern, severity), entries in document.groups.items()
            ),
            events_sha256=document.digest.hexdigest(),
        )

    @staticmethod
    def _validate(aggregates: Sequence[Aggregate]) -> tuple[EvidenceAggregate, ...]:
        selected: list[EvidenceAggregate] = []
        keys: set[tuple[str, str | None]] = set()
        sources: set[str | None] = set()
        for aggregate in aggregates:
            if not isinstance(aggregate, EvidenceAggregate):
                raise TypeError("aggregates must be EvidenceAggregate instances")
            key = _identity(aggregate)
            if key in keys:
                raise IntegrityError(
                    "duplicate aggregate for one event type and parser"
                )
            keys.add(key)
            sources.add(aggregate.source_id)
            selected.append(aggregate)
        if len(sources) > 1:
            raise IntegrityError("aggregates must come from exactly one source")
        return tuple(selected)

    @staticmethod
    def _retained_events(
        aggregates: Sequence[EvidenceAggregate],
    ) -> list[ParsedEvent]:
        retained: list[tuple[int, ParsedEvent]] = []
        for aggregate in aggregates:
            if not aggregate.retains_events:
                raise IntegrityError(
                    "aggregate does not retain its events; materialize it by "
                    "re-parsing the source with a reproducible parser"
                )
            for group in aggregate.groups:
                for entry in group.evidence:
                    retained.extend(zip(entry.sequence, entry.events, strict=True))
        retained.sort(key=lambda pair: pair[0])
        if [position for position, _ in retained] != list(range(len(retained))):
            raise IntegrityError("retained event positions are inconsistent")
        return [event for _, event in retained]

    @override
    async def materialize(
        self,
        aggregates: Sequence[Aggregate],
        events: Sequence[ParsedEvent] | None = None,
    ) -> tuple[ParsedEvent, ...]:
        """Rebuild every original event and verify it against ``aggregates``.

        Reproducible parsers pass the events of a fresh parse of the same
        source and context as ``events``; otherwise the retained events are
        used. Either way the aggregates are rebuilt from the candidate events
        and must match exactly, including the checksums. The order of
        ``aggregates`` does not matter, and an empty sequence represents a
        source without events.

        Args:
            aggregates: Every aggregate of one source document.
            events: Events of a fresh parse, for reproducible parsers.

        Returns:
            The verified original events in stream order.

        Raises:
            TypeError: If an aggregate is not an `EvidenceAggregate`.
            IntegrityError: If the aggregates are inconsistent or do not match
                the candidate events.
        """
        selected = self._validate(aggregates)
        candidates = (
            list(events) if events is not None else self._retained_events(selected)
        )
        try:
            rebuilt = await self.aggregate(candidates)
        except (TypeError, ValueError) as error:
            raise IntegrityError(f"events cannot be aggregated: {error}") from error
        if {_identity(item): item for item in rebuilt} != {
            _identity(item): item for item in selected
        }:
            raise IntegrityError(
                "events do not match the aggregate evidence or checksum; "
                "use the exact source, parser version, and parse context"
            )
        return tuple(candidates)

    @override
    async def merge(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[Aggregate, ...]:
        """Combine aggregates of distinct source documents.

        Args:
            partials: Aggregates to combine.

        Returns:
            The aggregates, unchanged and in input order.

        Raises:
            TypeError: If an item is not an `EvidenceAggregate`.
            CapabilityError: If two aggregates describe the same source,
                event type and parser, because a checksummed document cannot
                be split into partitions and merged.
        """
        if isinstance(partials, AsyncIterable):
            items: list[Aggregate] = [item async for item in partials]
        else:
            items = list(partials)
        seen: set[tuple[str | None, str, str | None]] = set()
        for item in items:
            if not isinstance(item, EvidenceAggregate):
                raise TypeError("partials must be EvidenceAggregate instances")
            key = (item.source_id, item.event_type, item.parser_name)
            if key in seen:
                raise CapabilityError(
                    "source documents are checksummed as a whole; aggregate each "
                    "complete source once instead of merging partitions"
                )
            seen.add(key)
        return tuple(items)
