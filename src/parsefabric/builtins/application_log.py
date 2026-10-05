"""Application log pattern parser."""

from __future__ import annotations

import re
from collections.abc import Iterable

from parsefabric.parser import DeterministicParser
from parsefabric.patterns import Pattern, RegexPattern

__all__ = [
    "ApplicationLogParser",
    "default_patterns",
]

# Everything up to the last non-whitespace character. Unlike ``(.*?)\s*$``,
# this form never re-scans whitespace runs, so matching stays linear.
_MESSAGE = r"(?P<message>(?:\S|\s+\S)*)"


def _signal(alternatives: str) -> str:
    """Match a line containing any alternative; the whole line is its message."""
    return rf"^(?=.*\b(?:{alternatives})\b){_MESSAGE}"


def default_patterns() -> tuple[RegexPattern, ...]:
    """Return the default application-log signal patterns.

    Returns:
        Fresh pattern instances, from the most to the least specific.
    """
    return (
        RegexPattern(
            "service_down",
            _signal(r"service down|service stopped|unavailable"),
            flags=re.IGNORECASE,
            priority=20,
            severity="ERROR",
        ),
        RegexPattern(
            "connection_failure",
            _signal(r"connection refused|connection reset|connect failed"),
            flags=re.IGNORECASE,
            priority=20,
            severity="ERROR",
        ),
        RegexPattern(
            "authentication_failure",
            _signal(r"authentication failed|invalid credentials|login failed"),
            flags=re.IGNORECASE,
            priority=20,
            severity="ERROR",
        ),
        RegexPattern(
            "authorization_failure",
            _signal(r"authorization failed|permission denied|forbidden"),
            flags=re.IGNORECASE,
            priority=20,
            severity="ERROR",
        ),
        RegexPattern(
            "timeout",
            _signal(r"timeout|timed out"),
            flags=re.IGNORECASE,
            priority=15,
            severity="ERROR",
        ),
        RegexPattern(
            "oom",
            _signal(r"OOM|out of memory"),
            flags=re.IGNORECASE,
            priority=15,
            severity="CRITICAL",
        ),
        RegexPattern(
            "retry",
            _signal(r"retry|retrying|attempt \d+"),
            flags=re.IGNORECASE,
            priority=10,
        ),
        RegexPattern(
            "stack_trace",
            r"^\s*(?P<message>Traceback \(most recent call last\):)",
            priority=10,
            severity="ERROR",
        ),
        RegexPattern(
            "error",
            r"\bERROR\b[: ]?\s*(?P<message>.*)",
            flags=re.IGNORECASE,
            priority=5,
            severity="ERROR",
        ),
        RegexPattern(
            "warning",
            r"\bWARN(?:ING)?\b[: ]?\s*(?P<message>.*)",
            flags=re.IGNORECASE,
            priority=5,
            severity="WARNING",
        ),
    )


class ApplicationLogParser(DeterministicParser):
    """Recognize common failure signals in free-form application logs.

    Every line is checked against every pattern, so one line can produce
    several events (for example ``timeout`` and ``error``). Signal patterns
    record the line without trailing whitespace as ``message``; ``error`` and
    ``warning`` record the text after the level.

    Args:
        patterns: Patterns to use instead of `default_patterns`; an
            empty sequence means no patterns.
    """

    def __init__(self, patterns: Iterable[Pattern] | None = None) -> None:
        super().__init__(
            default_patterns() if patterns is None else patterns,
            name="application-log",
        )
