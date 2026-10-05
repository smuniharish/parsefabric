"""Command-output parser: jc's command parsers or caller-provided patterns."""

from __future__ import annotations

from collections.abc import Sequence
from typing import override

import jc

from parsefabric._json import copy_json
from parsefabric.capabilities import ParserCapabilities
from parsefabric.errors import ConfigurationError, ParseError, ParseIssue
from parsefabric.models import (
    JSONValue,
    ParseContext,
    ParsedEvent,
    ParseResult,
    PatternStatistic,
)
from parsefabric.parser import DeterministicParser
from parsefabric.patterns import Pattern


def _records(output: object, command: str) -> list[dict[str, JSONValue]]:
    records = ([output] if output else []) if isinstance(output, dict) else output
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ParseError(f"jc {command!r} returned non-JSON records")
    try:
        return [copy_json(record, f"jc {command!r} record") for record in records]
    except ValueError as error:
        raise ParseError(str(error)) from error


class CLIOutputParser(DeterministicParser):
    """Parse command output with a jc command parser or line patterns.

    With ``command`` (for example ``command="df"``), the output is parsed by
    [jc](https://github.com/kellyjonbrazil/jc) as one document (tables need
    their header row), so each jc record becomes one ``cli_record`` event
    whose attributes are the record and whose evidence spans the output.
    Output that jc cannot parse becomes one ``unparsed`` event plus a
    `ParseIssue`; non-blank output in which jc finds no records produces a
    warning. With ``patterns``, every line is
    matched like a `DeterministicParser`.

    Args:
        patterns: Line patterns; mutually exclusive with ``command``.
        command: Name of a jc parser, such as ``"df"`` or ``"kv"``; see
            ``jc.parser_mod_list()``. Streaming parsers (``*_s``) are rejected.
        name: Parser name recorded in evidence.

    Raises:
        ValueError: If both or neither of ``patterns`` and ``command`` are
            given, or the command is unknown or streaming.
    """

    def __init__(
        self,
        patterns: Sequence[Pattern] | None = None,
        *,
        command: str | None = None,
        name: str = "cli-output",
    ) -> None:
        if (patterns is None) == (command is None):
            raise ValueError("provide exactly one of patterns or command")
        if command is not None:
            if command not in jc.parser_mod_list():
                raise ValueError(
                    f"unknown jc command parser {command!r}; see jc.parser_mod_list()"
                )
            if command.endswith("_s"):
                raise ValueError(
                    f"{command!r} is a streaming jc parser; use {command[:-2]!r}"
                )
        self._command = command
        super().__init__(
            patterns or (),
            name=name,
            capabilities=(
                None
                if command is None
                else ParserCapabilities(
                    deterministic=True, parallel_safe=True, aggregatable=True
                )
            ),
        )

    @property
    def command(self) -> str | None:
        """The jc parser name, or ``None`` when parsing with patterns."""
        return self._command

    @override
    def register_pattern(self, pattern: Pattern, *, replace: bool = False) -> None:
        if self._command is not None:
            raise ConfigurationError("a jc command parser does not use patterns")
        super().register_pattern(pattern, replace=replace)

    @override
    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        command = self._command
        if command is None:
            return await super().parse(source, context)
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="strict")
        elif isinstance(source, str):
            text = source
        else:
            raise TypeError("command output parsers accept only str or bytes")
        start = context.source_offset if context and context.source_offset else 0
        end = start + len(text.encode("utf-8"))
        try:
            records = _records(jc.parse(command, text, quiet=True), command)
        except Exception as error:  # jc parsers raise arbitrary errors on bad input
            event = self._with_parser_evidence(
                ParsedEvent("unparsed", attributes={"text": text}),
                context,
                start_offset=start,
                end_offset=end,
                pattern_name=command,
            )
            return ParseResult(
                events=(event,),
                errors=(
                    ParseIssue.from_exception(
                        error, source_id=context.source_id if context else None
                    ),
                ),
                parser_name=self.name,
                parser_version=self.version,
                correlation_id=context.correlation_id if context else None,
            )
        return ParseResult(
            events=tuple(
                self._with_parser_evidence(
                    ParsedEvent("cli_record", attributes=record),
                    context,
                    start_offset=start,
                    end_offset=end,
                    pattern_name=command,
                )
                for record in records
            ),
            warnings=(
                (f"jc {command!r} found no records in non-blank output",)
                if not records and text.strip()
                else ()
            ),
            pattern_statistics=(PatternStatistic(command, len(records)),),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
