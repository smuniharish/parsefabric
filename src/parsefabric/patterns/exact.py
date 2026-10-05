"""Exact-value pattern."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, override

from parsefabric._json import copy_json
from parsefabric.patterns.base import Pattern
from parsefabric.patterns.match import PatternMatch


class ExactPattern(Pattern):
    """Match a value equal to an expected text or structured value.

    Args:
        name: Pattern name.
        expected: Value compared with ``==``.
        priority: Evaluation priority; higher runs first.
        metadata: Free-form description kept on the pattern.
        event_type: Event type of produced events; defaults to ``name``.
        attributes: JSON-compatible attributes of produced events.
        severity: Severity of produced events.

    Raises:
        ValueError: If ``attributes`` are not JSON-compatible or ``severity``
            is not a string or ``None``.
    """

    def __init__(
        self,
        name: str,
        expected: object,
        *,
        priority: int = 0,
        metadata: Mapping[str, Any] | None = None,
        event_type: str | None = None,
        attributes: Mapping[str, Any] | None = None,
        severity: str | None = None,
    ) -> None:
        super().__init__(
            name, priority=priority, metadata=metadata, event_type=event_type
        )
        if severity is not None and not isinstance(severity, str):
            raise ValueError("pattern severity must be a string or None")
        self._expected = expected
        self._attributes = copy_json(dict(attributes or {}), "pattern attributes")
        self._severity = severity

    @property
    def expected(self) -> object:
        """The value a match must equal."""
        return self._expected

    @override
    def match(self, value: object) -> PatternMatch | None:
        if value != self._expected:
            return None
        return PatternMatch(
            attributes=copy_json(self._attributes), severity=self._severity
        )
