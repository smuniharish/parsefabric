"""Immutable, JSON-compatible parse models: context, evidence, events and results."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Self

from parsefabric._json import (
    JSONScalar,
    JSONValue,
    check_text,
    copy_json,
    require_object,
)
from parsefabric.errors import ParseIssue

__all__ = [
    "SCHEMA_VERSION",
    "Attributes",
    "Evidence",
    "JSONScalar",
    "JSONValue",
    "ParseContext",
    "ParseResult",
    "ParsedEvent",
    "PatternStatistic",
]

type Attributes = dict[str, JSONValue]

SCHEMA_VERSION = "1"
"""Version of the event and parse result JSON representations."""


def _check_identifiers(what: str, *values: object) -> None:
    for value in values:
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{what} must be strings")
            if not value.isascii():
                check_text(value, what)


def _check_integer(value: object, name: str, *, minimum: int) -> None:
    if value is not None and (type(value) is not int or value < minimum):
        requirement = "a non-negative" if minimum == 0 else "a positive"
        raise ValueError(f"{name} must be {requirement} integer")


def _tuple_of[T](values: object, kind: type[T], what: str) -> tuple[T, ...]:
    if not isinstance(values, (tuple, list)):
        raise ValueError(f"{what} must be a tuple")
    if any(not isinstance(item, kind) for item in values):
        raise ValueError(f"{what} must contain only {kind.__name__} items")
    return tuple(values)


def _optional_time(value: object, what: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{what} must be an ISO 8601 string or null")
    return datetime.fromisoformat(value)


@dataclass(frozen=True, slots=True)
class ParseContext:
    """Caller-supplied description of where one input comes from.

    Attributes:
        source_id: Identifier of the source document; recorded in evidence.
        correlation_id: Identifier that correlates related parses.
        partition_id: Identifier of the partition this input belongs to.
        source_offset: UTF-8 byte offset of the input within its source
            document. Event offsets are reported relative to the document.
    """

    source_id: str | None = None
    correlation_id: str | None = None
    partition_id: str | None = None
    source_offset: int | None = None

    def __post_init__(self) -> None:
        _check_identifiers(
            "source, correlation, and partition identifiers",
            self.source_id,
            self.correlation_id,
            self.partition_id,
        )
        _check_integer(self.source_offset, "source_offset", minimum=0)


_EVIDENCE_FIELDS = frozenset(
    (
        "source_id",
        "start_offset",
        "end_offset",
        "line_number",
        "parser_name",
        "parser_version",
        "pattern_name",
        "partition_id",
        "correlation_id",
    )
)


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where an event came from and which parser and pattern produced it.

    Offsets are UTF-8 byte offsets into the source document; ``end_offset``
    is exclusive. Line numbers are one-based and identify the first line of
    the event.

    Attributes:
        source_id: Source document identifier.
        start_offset: Byte offset where the event's text starts.
        end_offset: Byte offset just after the event's text.
        line_number: First source line of the event.
        parser_name: Name of the parser that produced the event.
        parser_version: Version of that parser.
        pattern_name: Pattern or route that matched.
        partition_id: Partition the event was parsed in.
        correlation_id: Correlation identifier of the parse.
    """

    source_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    line_number: int | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    pattern_name: str | None = None
    partition_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        _check_identifiers(
            "evidence identifiers",
            self.source_id,
            self.parser_name,
            self.parser_version,
            self.pattern_name,
            self.partition_id,
            self.correlation_id,
        )
        _check_integer(self.start_offset, "start_offset", minimum=0)
        _check_integer(self.end_offset, "end_offset", minimum=0)
        _check_integer(self.line_number, "line_number", minimum=1)
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset must not precede start_offset")

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the JSON-compatible representation."""
        return {
            "source_id": self.source_id,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "line_number": self.line_number,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "pattern_name": self.pattern_name,
            "partition_id": self.partition_id,
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Rebuild evidence from `to_dict` output.

        Args:
            data: A decoded JSON object.

        Returns:
            The validated value.

        Raises:
            ValueError: If ``data`` does not have exactly the evidence fields
                or a field is invalid.
        """
        return cls(**require_object(data, "evidence", _EVIDENCE_FIELDS))


_EVENT_FIELDS = frozenset(
    (
        "schema_version",
        "event_type",
        "attributes",
        "timestamp",
        "severity",
        "confidence",
        "evidence",
    )
)
_NO_EVIDENCE = Evidence()


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    """One normalized finding with its details and provenance.

    ``attributes`` are validated and copied when the event is created, so a
    mapping the caller keeps using cannot change the event. Treat the
    attributes of an event as read-only.

    Attributes:
        event_type: Kind of finding, such as ``"timeout"``.
        attributes: JSON-compatible details.
        timestamp: Timezone-aware time of the finding, if known.
        severity: Severity label, if any.
        confidence: Confidence between 0 and 1, for parsers that estimate it.
        evidence: Where the event came from.
    """

    event_type: str
    attributes: Attributes = field(default_factory=dict)
    timestamp: datetime | None = None
    severity: str | None = None
    confidence: float | None = None
    evidence: Evidence = _NO_EVIDENCE

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, str) or not self.event_type:
            raise ValueError("event_type must be a non-empty string")
        check_text(self.event_type, "event_type")
        if not isinstance(self.attributes, dict):
            raise ValueError("event attributes must be a JSON object")
        object.__setattr__(
            self, "attributes", copy_json(self.attributes, "event attributes")
        )
        if self.timestamp is not None and (
            not isinstance(self.timestamp, datetime)
            or self.timestamp.utcoffset() is None
        ):
            raise ValueError("event timestamps must be timezone-aware datetimes")
        if self.severity is not None:
            if not isinstance(self.severity, str):
                raise ValueError("event severity must be a string")
            check_text(self.severity, "event severity")
        if self.confidence is not None and (
            not isinstance(self.confidence, (int, float))
            or isinstance(self.confidence, bool)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be a number between 0 and 1")
        if not isinstance(self.evidence, Evidence):
            raise ValueError("event evidence must be an Evidence instance")

    def with_evidence(self, evidence: Evidence) -> ParsedEvent:
        """Return a copy of the event with different evidence.

        Args:
            evidence: The replacement evidence.

        Returns:
            A new event sharing this event's validated payload.

        Raises:
            ValueError: If ``evidence`` is not an `Evidence`.
        """
        if not isinstance(evidence, Evidence):
            raise ValueError("event evidence must be an Evidence instance")
        if type(self) is not ParsedEvent:
            return replace(self, evidence=evidence)
        event = object.__new__(ParsedEvent)
        object.__setattr__(event, "event_type", self.event_type)
        object.__setattr__(event, "attributes", self.attributes)
        object.__setattr__(event, "timestamp", self.timestamp)
        object.__setattr__(event, "severity", self.severity)
        object.__setattr__(event, "confidence", self.confidence)
        object.__setattr__(event, "evidence", evidence)
        return event

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the JSON-compatible representation with copied attributes."""
        data = self._to_wire()
        data["attributes"] = copy_json(self.attributes)
        return data

    def _to_wire(self) -> dict[str, JSONValue]:
        """Return the representation sharing attributes, for immediate encoding."""
        return {
            "schema_version": SCHEMA_VERSION,
            "event_type": self.event_type,
            "attributes": self.attributes,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "severity": self.severity,
            "confidence": self.confidence,
            "evidence": self.evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Rebuild an event from `to_dict` output.

        Args:
            data: A decoded JSON object.

        Returns:
            The validated value.

        Raises:
            ValueError: If ``data`` does not have exactly the event fields, has
                an unsupported schema version, or a field is invalid.
        """
        fields = require_object(data, "event", _EVENT_FIELDS)
        if fields["schema_version"] != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported event schema version: {fields['schema_version']!r}"
            )
        return cls(
            event_type=fields["event_type"],
            attributes=fields["attributes"],
            timestamp=_optional_time(fields["timestamp"], "event timestamp"),
            severity=fields["severity"],
            confidence=fields["confidence"],
            evidence=Evidence.from_dict(fields["evidence"]),
        )


_STATISTIC_FIELDS = frozenset(("pattern_name", "matches"))


@dataclass(frozen=True, slots=True)
class PatternStatistic:
    """Number of successful matches of one named pattern in a parse call.

    Attributes:
        pattern_name: Name of the pattern or route.
        matches: Number of matches, zero or more.
    """

    pattern_name: str
    matches: int

    def __post_init__(self) -> None:
        if not isinstance(self.pattern_name, str) or not self.pattern_name:
            raise ValueError("pattern name must be a non-empty string")
        check_text(self.pattern_name, "pattern name")
        if type(self.matches) is not int or self.matches < 0:
            raise ValueError("match count must be a non-negative integer")

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the JSON-compatible representation."""
        return {"pattern_name": self.pattern_name, "matches": self.matches}

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Rebuild a statistic from `to_dict` output.

        Args:
            data: A decoded JSON object.

        Returns:
            The validated value.

        Raises:
            ValueError: If ``data`` is not a valid statistic object.
        """
        return cls(**require_object(data, "pattern statistic", _STATISTIC_FIELDS))


_RESULT_FIELDS = frozenset(
    (
        "schema_version",
        "parser_name",
        "parser_version",
        "correlation_id",
        "llm_result",
        "events",
        "warnings",
        "errors",
        "pattern_statistics",
    )
)


def _list(fields: dict[str, Any], name: str) -> list[Any]:
    value = fields[name]
    if not isinstance(value, list):
        raise ValueError(f"result {name} must be an array")
    return value


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Events parsed from one input, with explicit issues and statistics.

    Sequences given as lists are stored as tuples.

    Attributes:
        events: Parsed events in source order.
        warnings: Non-fatal messages.
        errors: Failures recorded instead of raised.
        pattern_statistics: Match counts, one per distinct pattern name.
        parser_name: Name of the parser that produced the result.
        parser_version: Version of that parser.
        correlation_id: Correlation identifier of the parse.
        llm_result: Optional model-written summary attached by
            `parsefabric.summarization.EvidenceSummarizer.summarize_result`.
    """

    events: tuple[ParsedEvent, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[ParseIssue, ...] = ()
    pattern_statistics: tuple[PatternStatistic, ...] = ()
    parser_name: str | None = None
    parser_version: str | None = None
    correlation_id: str | None = None
    llm_result: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "events", _tuple_of(self.events, ParsedEvent, "result events")
        )
        warnings = _tuple_of(self.warnings, str, "result warnings")
        for warning in warnings:
            check_text(warning, "result warnings")
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(
            self, "errors", _tuple_of(self.errors, ParseIssue, "result errors")
        )
        statistics = _tuple_of(
            self.pattern_statistics, PatternStatistic, "result pattern statistics"
        )
        names = [statistic.pattern_name for statistic in statistics]
        if len(names) != len(set(names)):
            raise ValueError("result pattern statistics must have unique names")
        object.__setattr__(self, "pattern_statistics", statistics)
        _check_identifiers(
            "result parser and correlation identifiers",
            self.parser_name,
            self.parser_version,
            self.correlation_id,
        )
        if self.llm_result is not None and (
            not isinstance(self.llm_result, str) or not self.llm_result.strip()
        ):
            raise ValueError("llm_result must be non-empty text or None")
        if self.llm_result is not None:
            check_text(self.llm_result, "llm_result")

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the JSON-compatible representation with copied attributes."""
        data = self._to_wire()
        data["events"] = [event.to_dict() for event in self.events]
        return data

    def _to_wire(self) -> dict[str, JSONValue]:
        """Return the representation sharing attributes, for immediate encoding."""
        return {
            "schema_version": SCHEMA_VERSION,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "correlation_id": self.correlation_id,
            "llm_result": self.llm_result,
            "events": [event._to_wire() for event in self.events],
            "warnings": list(self.warnings),
            "errors": [issue.to_dict() for issue in self.errors],
            "pattern_statistics": [
                statistic.to_dict() for statistic in self.pattern_statistics
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Rebuild a result from `to_dict` output.

        Args:
            data: A decoded JSON object.

        Returns:
            The validated value.

        Raises:
            ValueError: If ``data`` does not have exactly the result fields,
                has an unsupported schema version, or a field is invalid.
        """
        fields = require_object(data, "parse result", _RESULT_FIELDS)
        if fields["schema_version"] != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported result schema version: {fields['schema_version']!r}"
            )
        return cls(
            events=tuple(
                ParsedEvent.from_dict(item) for item in _list(fields, "events")
            ),
            warnings=tuple(_list(fields, "warnings")),
            errors=tuple(
                ParseIssue.from_dict(item) for item in _list(fields, "errors")
            ),
            pattern_statistics=tuple(
                PatternStatistic.from_dict(item)
                for item in _list(fields, "pattern_statistics")
            ),
            parser_name=fields["parser_name"],
            parser_version=fields["parser_version"],
            correlation_id=fields["correlation_id"],
            llm_result=fields["llm_result"],
        )
