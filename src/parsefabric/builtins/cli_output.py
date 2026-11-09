"""Command-output parser: a `CommandOutputBackend` such as jc, or line patterns."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, override

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
from parsefabric.parser._text import source_text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from parsefabric.patterns import Pattern


class CommandOutputBackend(ABC):
    """Turn the complete output of a command into JSON records.

    Implement `name`, `validate` and `parse` to parse command output with
    another library or service. `JcBackend` is the default.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name used in messages, such as ``"jc"``."""

    @abstractmethod
    def validate(self, command: str) -> None:
        """Check that ``command`` can be parsed, when a parser is configured.

        Raises:
            ValueError: If the backend cannot parse ``command`` output.
        """

    @abstractmethod
    async def parse(self, command: str, text: str) -> object:
        """Parse the output of ``command``.

        Returns:
            A JSON object or a list of JSON objects; an empty object or list
            means the output holds no records.

        Raises:
            Exception: Any error for output the backend cannot parse; the
                parser reports it as a `ParseIssue`.
        """


class JcBackend(CommandOutputBackend):
    """Parse command output with [jc](https://github.com/kellyjonbrazil/jc).

    Commands are jc parser names, such as ``"df"`` or ``"kv"``; see
    ``jc.parser_mod_list()``. Streaming parsers (``*_s``) are rejected
    because a parser receives the complete output. jc runs in a worker
    thread, so large outputs do not block the event loop.
    """

    @property
    @override
    def name(self) -> str:
        return "jc"

    @override
    def validate(self, command: str) -> None:
        if command not in jc.parser_mod_list():
            raise ValueError(f"unknown jc command parser {command!r}; see jc.parser_mod_list()")
        if command.endswith("_s"):
            raise ValueError(f"{command!r} is a streaming jc parser; use {command[:-2]!r}")

    @override
    async def parse(self, command: str, text: str) -> object:
        return await asyncio.to_thread(jc.parse, command, text, quiet=True)


DEFAULT_COMMAND_BACKEND = JcBackend()
"""The jc backend `CLIOutputParser` uses unless given another."""


def _records(output: object, label: str) -> list[dict[str, JSONValue]]:
    records = ([output] if output else []) if isinstance(output, dict) else output
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ParseError(f"{label} returned non-JSON records")
    try:
        return [copy_json(record, f"{label} record") for record in records]
    except ValueError as error:
        raise ParseError(str(error)) from error


class CLIOutputParser(DeterministicParser):
    """Parse command output with a `CommandOutputBackend` or line patterns.

    With ``command`` (for example ``command="df"``), the backend parses the
    output as one document (tables need their header row), so each record
    becomes one ``cli_record`` event whose attributes are the record and
    whose evidence spans the output. Output that the backend cannot parse
    becomes one ``unparsed`` event plus a `ParseIssue`; non-blank output in
    which the backend finds no records produces a warning. With
    ``patterns``, every line is matched like a `DeterministicParser`.

    Args:
        patterns: Line patterns; mutually exclusive with ``command``.
        command: Command whose output is parsed, such as ``"df"`` or
            ``"kv"`` with the default `JcBackend`.
        backend: Parses command output; defaults to `DEFAULT_COMMAND_BACKEND`.
        name: Parser name recorded in evidence.

    Raises:
        ValueError: If both or neither of ``patterns`` and ``command`` are
            given, or the backend rejects the command.
        TypeError: If ``backend`` is not a `CommandOutputBackend`.
    """

    def __init__(
        self,
        patterns: Sequence[Pattern] | None = None,
        *,
        command: str | None = None,
        backend: CommandOutputBackend = DEFAULT_COMMAND_BACKEND,
        name: str = "cli-output",
    ) -> None:
        if (patterns is None) == (command is None):
            raise ValueError("provide exactly one of patterns or command")
        if not isinstance(backend, CommandOutputBackend):
            raise TypeError("backend must be a CommandOutputBackend")
        if command is not None:
            backend.validate(command)
        self._command = command
        self._backend = backend
        super().__init__(
            patterns or (),
            name=name,
            capabilities=(
                None
                if command is None
                else ParserCapabilities(deterministic=True, parallel_safe=True, aggregatable=True)
            ),
        )

    @property
    def command(self) -> str | None:
        """The parsed command, or ``None`` when parsing with patterns."""
        return self._command

    @property
    def backend(self) -> CommandOutputBackend:
        """The backend that parses command output."""
        return self._backend

    @override
    def register_pattern(self, pattern: Pattern, *, replace: bool = False) -> None:
        if self._command is not None:
            raise ConfigurationError("a command output parser does not use patterns")
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
        text = source_text(source, "command output parser")
        start = context.source_offset if context and context.source_offset else 0
        end = start + len(text.encode("utf-8"))
        label = f"{self._backend.name} {command!r}"
        try:
            records = _records(await self._backend.parse(command, text), label)
        except Exception as error:  # backends such as jc raise arbitrary errors on bad input
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
                (f"{label} found no records in non-blank output",)
                if not records and text.strip()
                else ()
            ),
            pattern_statistics=(PatternStatistic(command, len(records)),),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
