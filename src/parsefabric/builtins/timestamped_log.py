"""Ordered timestamped logs with lossless, source-referenced aggregation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import ClassVar, override

from parsefabric.capabilities import ParserCapabilities
from parsefabric.errors import ParseError
from parsefabric.models import ParseContext, ParsedEvent, ParseResult
from parsefabric.parser import Parser
from parsefabric.parser._text import iter_text_lines


class TimestampedLogParser(Parser):
    """Parse a document of ``TIMESTAMP LEVEL message`` lines, one event per line.

    Every line must match the line pattern and carry a timezone-aware ISO
    8601 timestamp; otherwise parsing fails with
    `ParseError` naming the line. Each ``log``
    event records ``level`` and ``message`` attributes, the timestamp, the
    level as severity, and the line's exact byte span. The parser is
    deterministic, so aggregates store line positions instead of events.

    Args:
        line_pattern: Regular expression, as text or compiled, with ``at``,
            ``level`` and ``message`` named groups that must match a whole
            line. Defaults to `DEFAULT_LINE_PATTERN`.

    Raises:
        TypeError: If ``line_pattern`` is not a text regex.
        ValueError: If the pattern lacks a required group.
    """

    DEFAULT_LINE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?P<at>\S+)\s+(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)"
        r"\s+(?P<message>.+)$"
    )
    """Default line pattern: an ISO 8601 timestamp, a level and the message."""

    def __init__(
        self,
        *,
        line_pattern: str | re.Pattern[str] | None = None,
    ) -> None:
        if line_pattern is not None and not isinstance(line_pattern, (str, re.Pattern)):
            raise TypeError("line_pattern must be a string or compiled text regex")
        if isinstance(line_pattern, re.Pattern) and not isinstance(
            line_pattern.pattern, str
        ):
            raise TypeError("line_pattern must be a text regex")
        self._line_pattern = (
            self.DEFAULT_LINE_PATTERN
            if line_pattern is None
            else (
                re.compile(line_pattern)
                if isinstance(line_pattern, str)
                else line_pattern
            )
        )
        if not {"at", "level", "message"} <= self._line_pattern.groupindex.keys():
            raise ValueError("line_pattern requires at, level, and message groups")

    @property
    @override
    def name(self) -> str:
        return "timestamped-log"

    @property
    @override
    def version(self) -> str:
        return "1"

    @property
    @override
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(
            deterministic=True, parallel_safe=True, aggregatable=True
        )

    @override
    async def parse(
        self, source: object, context: ParseContext | None = None
    ) -> ParseResult:
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="strict")
        elif isinstance(source, str):
            text = source
        else:
            raise TypeError("timestamped log parser accepts only str or bytes")
        offset = context.source_offset if context and context.source_offset else 0
        events: list[ParsedEvent] = []
        for line_number, (line, width) in enumerate(iter_text_lines(text), 1):
            match = self._line_pattern.fullmatch(line)
            if match is None:
                raise ParseError(f"invalid timestamped log at line {line_number}")
            if not all(match.group(name) for name in ("at", "level", "message")):
                raise ParseError(f"incomplete timestamped log at line {line_number}")
            try:
                timestamp = datetime.fromisoformat(match["at"])
            except ValueError as error:
                raise ParseError(
                    f"invalid log timestamp at line {line_number}"
                ) from error
            if timestamp.utcoffset() is None:
                raise ParseError(
                    f"log timestamp must have a timezone at line {line_number}"
                )
            event = ParsedEvent(
                event_type="log",
                timestamp=timestamp,
                severity=match["level"],
                attributes={
                    "level": match["level"],
                    "message": match["message"],
                },
            )
            events.append(
                self._with_parser_evidence(
                    event,
                    context,
                    line_number=line_number,
                    start_offset=offset,
                    end_offset=offset + width,
                    pattern_name="timestamped-log",
                )
            )
            offset += width
        return ParseResult(
            events=tuple(events),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
