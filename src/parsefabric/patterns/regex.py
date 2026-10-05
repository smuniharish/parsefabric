"""Regular-expression pattern for text records."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, override

from parsefabric.patterns.base import Pattern
from parsefabric.patterns.match import PatternMatch


class RegexPattern(Pattern):
    """Match text with a regular expression; named groups become attributes.

    The expression is applied with `re.Pattern.search`, so anchor it
    with ``^`` to match from the start of a line. Groups that did not
    participate in the match are omitted. Prefer expressions without nested
    or overlapping quantifiers: matching runs on untrusted input and Python's
    regular expressions have no timeout.

    Args:
        name: Pattern name.
        expression: Regular expression source.
        flags: `re` flags.
        priority: Evaluation priority; higher runs first.
        metadata: Free-form description kept on the pattern.
        event_type: Event type of produced events; defaults to ``name``.
        severity: Severity of produced events.

    Raises:
        ValueError: If ``expression`` is not a string or ``severity`` is not a
            string or ``None``.
        re.error: If the expression is invalid.
    """

    def __init__(
        self,
        name: str,
        expression: str,
        *,
        flags: int = 0,
        priority: int = 0,
        metadata: Mapping[str, Any] | None = None,
        event_type: str | None = None,
        severity: str | None = None,
    ) -> None:
        super().__init__(
            name, priority=priority, metadata=metadata, event_type=event_type
        )
        if not isinstance(expression, str):
            raise ValueError("regex pattern expression must be a string")
        if severity is not None and not isinstance(severity, str):
            raise ValueError("pattern severity must be a string or None")
        self._compiled = re.compile(expression, flags)
        self._severity = severity

    @property
    def expression(self) -> str:
        """Source of the regular expression."""
        return self._compiled.pattern

    @property
    def flags(self) -> int:
        """Compiled `re` flags."""
        return self._compiled.flags

    @override
    def match(self, value: object) -> PatternMatch | None:
        if not isinstance(value, str):
            return None
        found = self._compiled.search(value)
        if found is None:
            return None
        attributes = {
            key: item for key, item in found.groupdict().items() if item is not None
        }
        return PatternMatch(attributes=attributes, severity=self._severity)
