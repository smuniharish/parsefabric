"""Common named pattern contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from parsefabric.models import ParsedEvent
from parsefabric.patterns.match import PatternMatch


class Pattern(ABC):
    """A named, prioritized rule that recognizes one kind of value.

    Parsers evaluate patterns in descending ``priority`` order, then by name.
    A pattern's identity is fixed when it is created.

    Args:
        name: Non-empty name, unique within a parser.
        priority: Evaluation priority; higher runs first.
        metadata: Free-form description kept on the pattern, never copied
            into events.
        event_type: Event type of produced events; defaults to ``name``.

    Raises:
        ValueError: If ``name`` or ``event_type`` is empty or not a string,
            or ``priority`` is not an integer.
    """

    def __init__(
        self,
        name: str,
        *,
        priority: int = 0,
        metadata: Mapping[str, Any] | None = None,
        event_type: str | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("pattern name must be a non-empty string")
        if type(priority) is not int:
            raise ValueError("pattern priority must be an integer")
        if event_type is not None and (
            not isinstance(event_type, str) or not event_type
        ):
            raise ValueError("pattern event_type must be a non-empty string")
        self._name = name
        self._priority = priority
        self._metadata = dict(metadata or {})
        self._event_type = event_type or name

    @property
    def name(self) -> str:
        """Name of the pattern, unique within a parser."""
        return self._name

    @property
    def priority(self) -> int:
        """Evaluation priority; higher runs first."""
        return self._priority

    @property
    def metadata(self) -> Mapping[str, Any]:
        """Read-only free-form description of the pattern."""
        return MappingProxyType(self._metadata)

    @property
    def event_type(self) -> str:
        """Event type of events created by `to_event`."""
        return self._event_type

    @abstractmethod
    def match(self, value: object) -> PatternMatch | None:
        """Return match data for ``value``, or ``None`` if it does not match.

        Args:
            value: A line of text or a structured value.

        Returns:
            Attributes, severity and confidence of the match, or ``None``.
        """

    def to_event(self, match: PatternMatch) -> ParsedEvent:
        """Create an event from a match; parsers add the evidence.

        Args:
            match: Result of `match`.

        Returns:
            An event with the match's attributes, severity and confidence.
        """
        return ParsedEvent(
            event_type=self._event_type,
            attributes=match.attributes,
            severity=match.severity,
            confidence=match.confidence,
        )
