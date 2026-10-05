"""Predicate-driven pattern and extractor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, override

from parsefabric.patterns.base import Pattern
from parsefabric.patterns.match import PatternMatch


class PredicatePattern(Pattern):
    """Match values accepted by a caller-supplied predicate.

    Parsers that contain a predicate pattern are only as deterministic and
    thread-safe as the callables.

    Args:
        name: Pattern name.
        predicate: Returns whether a value matches.
        extractor: Returns the attributes of a matched value; defaults to no
            attributes.
        priority: Evaluation priority; higher runs first.
        metadata: Free-form description kept on the pattern.
        event_type: Event type of produced events; defaults to ``name``.
        severity: Severity of produced events.

    Raises:
        ValueError: If a callable is not callable or ``severity`` is not a
            string or ``None``.
    """

    def __init__(
        self,
        name: str,
        predicate: Callable[[object], bool],
        extractor: Callable[[object], Mapping[str, Any]] | None = None,
        *,
        priority: int = 0,
        metadata: Mapping[str, Any] | None = None,
        event_type: str | None = None,
        severity: str | None = None,
    ) -> None:
        super().__init__(
            name, priority=priority, metadata=metadata, event_type=event_type
        )
        if not callable(predicate) or (
            extractor is not None and not callable(extractor)
        ):
            raise ValueError("predicate and extractor must be callable")
        if severity is not None and not isinstance(severity, str):
            raise ValueError("pattern severity must be a string or None")
        self._predicate = predicate
        self._extractor = extractor
        self._severity = severity

    @override
    def match(self, value: object) -> PatternMatch | None:
        if not self._predicate(value):
            return None
        attributes = {} if self._extractor is None else dict(self._extractor(value))
        return PatternMatch(attributes=attributes, severity=self._severity)
