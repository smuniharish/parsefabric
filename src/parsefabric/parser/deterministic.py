"""Ordered deterministic pattern parser."""

from __future__ import annotations

from collections.abc import Iterable
from threading import RLock
from typing import override

from parsefabric.capabilities import ParserCapabilities
from parsefabric.errors import ConfigurationError
from parsefabric.models import ParseContext, ParsedEvent, ParseResult, PatternStatistic
from parsefabric.parser._text import iter_text_lines
from parsefabric.parser.base import Parser, validated_identity
from parsefabric.patterns import Pattern


def _ordered(patterns: Iterable[Pattern]) -> tuple[Pattern, ...]:
    return tuple(
        sorted(patterns, key=lambda pattern: (-pattern.priority, pattern.name))
    )


class DeterministicParser(Parser):
    """Apply an ordered set of patterns to every line of a text document.

    Each line is matched against every pattern in descending priority order
    (ties broken by name); each match becomes one event whose evidence
    records the line number, the UTF-8 byte span of the line including its
    terminator, and the pattern name. Lines are split on the same boundaries
    as `str.splitlines`.

    Args:
        patterns: Initial patterns; names must be unique.
        name: Non-empty parser name.
        version: Non-empty parser version.
        first_match_only: Stop at the first matching pattern on each line.
        capabilities: Explicit capabilities. Defaults to deterministic,
            incremental, parallel-safe, line-partitionable and aggregatable.

    Raises:
        ValueError: If the name or version is empty, pattern names repeat, or
            the capabilities are not deterministic.
        TypeError: If an argument has the wrong type.
    """

    def __init__(
        self,
        patterns: Iterable[Pattern],
        *,
        name: str,
        version: str = "1",
        first_match_only: bool = False,
        capabilities: ParserCapabilities | None = None,
    ) -> None:
        self._name, self._version = validated_identity(name, version)
        selected = tuple(patterns)
        if any(not isinstance(pattern, Pattern) for pattern in selected):
            raise TypeError("patterns must be Pattern instances")
        names = [pattern.name for pattern in selected]
        if len(names) != len(set(names)):
            raise ValueError("pattern names must be unique within a parser")
        if not isinstance(first_match_only, bool):
            raise TypeError("first_match_only must be a bool")
        if capabilities is not None and not isinstance(
            capabilities, ParserCapabilities
        ):
            raise TypeError("capabilities must be ParserCapabilities")
        self._patterns = _ordered(selected)
        self._first_match_only = first_match_only
        self._pattern_lock = RLock()
        self._capabilities = capabilities or ParserCapabilities(
            deterministic=True,
            incremental=True,
            parallel_safe=True,
            partitionable=True,
            partition_framing="line",
            aggregatable=True,
        )
        if not self._capabilities.deterministic:
            raise ValueError("DeterministicParser requires deterministic capability")

    @property
    @override
    def name(self) -> str:
        return self._name

    @property
    @override
    def version(self) -> str:
        return self._version

    @property
    @override
    def capabilities(self) -> ParserCapabilities:
        return self._capabilities

    @property
    def patterns(self) -> tuple[Pattern, ...]:
        """Patterns in the order they are evaluated."""
        with self._pattern_lock:
            return self._patterns

    def register_pattern(self, pattern: Pattern, *, replace: bool = False) -> None:
        """Add a pattern, or replace one with the same name when ``replace``.

        Args:
            pattern: Pattern to add.
            replace: Replace a pattern with the same name.

        Raises:
            TypeError: If ``pattern`` is not a `Pattern`.
            ConfigurationError: If the name is taken and ``replace`` is false.
        """
        if not isinstance(pattern, Pattern):
            raise TypeError("pattern must be a Pattern instance")
        with self._pattern_lock:
            current = {item.name: item for item in self._patterns}
            if pattern.name in current and not replace:
                raise ConfigurationError(
                    f"pattern {pattern.name!r} is already registered"
                )
            current[pattern.name] = pattern
            self._patterns = _ordered(current.values())

    def unregister_pattern(self, name: str) -> Pattern:
        """Remove and return the pattern called ``name``.

        Args:
            name: Name of the pattern.

        Returns:
            The removed pattern.

        Raises:
            ConfigurationError: If no pattern has that name.
        """
        with self._pattern_lock:
            current = {item.name: item for item in self._patterns}
            try:
                removed = current.pop(name)
            except KeyError as error:
                raise ConfigurationError(
                    f"pattern {name!r} is not registered"
                ) from error
            self._patterns = _ordered(current.values())
            return removed

    def __getstate__(self) -> dict[str, object]:
        state = self.__dict__.copy()
        state.pop("_pattern_lock")
        return state

    def __setstate__(self, state: dict[str, object]) -> None:
        self.__dict__.update(state)
        self._pattern_lock = RLock()

    @override
    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        """Match every line of a text document against the patterns.

        Args:
            source: Text or UTF-8 bytes.
            context: Source description; ``source_offset`` shifts offsets.

        Returns:
            One event per match, in line order, and the match count of every
            pattern.

        Raises:
            TypeError: If ``source`` is not text or bytes.
            UnicodeError: If bytes are not UTF-8 or text is not valid Unicode.
        """
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="strict")
        elif isinstance(source, str):
            text = source
        else:
            raise TypeError("deterministic text parsers accept only str or bytes")

        events: list[ParsedEvent] = []
        patterns = self.patterns
        matches: dict[str, int] = {pattern.name: 0 for pattern in patterns}
        byte_offset = context.source_offset if context and context.source_offset else 0
        for line_number, (content, line_width) in enumerate(
            iter_text_lines(text),
            start=1,
        ):
            start_offset = byte_offset
            byte_offset += line_width
            for pattern in patterns:
                match = pattern.match(content)
                if match is None:
                    continue
                matches[pattern.name] += 1
                events.append(
                    self._with_parser_evidence(
                        pattern.to_event(match),
                        context,
                        start_offset=start_offset,
                        end_offset=byte_offset,
                        line_number=line_number,
                        pattern_name=pattern.name,
                    )
                )
                if self._first_match_only:
                    break
        return ParseResult(
            events=tuple(events),
            pattern_statistics=tuple(
                PatternStatistic(name, count) for name, count in sorted(matches.items())
            ),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
