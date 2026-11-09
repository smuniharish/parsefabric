"""A parser to copy and adapt: one event per ``key=value`` record line.

Replace ``RECORD`` and ``to_event`` with your format. Keep the evidence:
every event records its line number and UTF-8 byte span, so stored
aggregates can be rebuilt and checked against the source. Bump ``VERSION``
whenever the events produced for the same input change.

Lines that do not parse are reported in ``ParseResult.errors`` instead of
being dropped, so a batch keeps going and nothing disappears silently.
"""

from __future__ import annotations

import re
from typing import override

from parsefabric import (
    Evidence,
    ParseContext,
    ParsedEvent,
    ParseIssue,
    Parser,
    ParserCapabilities,
    ParseResult,
)

NAME = "key-value"
VERSION = "1"
FIELD = re.compile(r'(\w+)=("[^"]*"|\S+)')
RECORD = re.compile(r'^\s*(?:\w+=(?:"[^"]*"|\S+)\s*)+$')
SEVERITIES = {"debug": "DEBUG", "info": "INFO", "warn": "WARNING", "error": "ERROR"}


def to_event(fields: dict[str, str]) -> ParsedEvent:
    level = fields.get("level", "info").lower()
    return ParsedEvent(
        event_type=fields.get("event", "record"),
        attributes=dict(fields),
        severity=SEVERITIES.get(level, level.upper()),
    )


class KeyValueParser(Parser):
    """Parse ``key=value`` records, one per line; quoted values may hold spaces."""

    @property
    @override
    def name(self) -> str:
        return NAME

    @property
    @override
    def version(self) -> str:
        return VERSION

    @property
    @override
    def capabilities(self) -> ParserCapabilities:
        # Promise only what holds: the same input always gives the same events,
        # parse keeps no state between calls, and each line stands alone.
        return ParserCapabilities(
            deterministic=True,
            parallel_safe=True,
            aggregatable=True,
            partitionable=True,
            partition_framing="line",
        )

    @override
    async def parse(self, source: object, context: ParseContext | None = None) -> ParseResult:
        if not isinstance(source, str):
            raise TypeError("key-value records must be text")
        offset = (context.source_offset if context else None) or 0
        events: list[ParsedEvent] = []
        issues: list[ParseIssue] = []
        for number, line in enumerate(source.splitlines(keepends=True), start=1):
            size = len(line.encode("utf-8"))
            record = line.rstrip("\r\n")
            if record.strip():
                if RECORD.match(record):
                    fields = {key: value.strip('"') for key, value in FIELD.findall(record)}
                    evidence = Evidence(
                        line_number=number,
                        start_offset=offset,
                        end_offset=offset + len(record.encode("utf-8")),
                        pattern_name="record",
                    )
                    events.append(to_event(fields).with_evidence(evidence))
                else:
                    issues.append(
                        ParseIssue(
                            error_type="InvalidRecord",
                            message=f"line {number} is not a key=value record",
                            source_id=context.source_id if context else None,
                        )
                    )
            offset += size
        return ParseResult(events=tuple(events), errors=tuple(issues))
