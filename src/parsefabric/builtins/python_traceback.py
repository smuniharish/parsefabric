"""Python traceback parser."""

from __future__ import annotations

import re
from typing import override

from parsefabric.capabilities import ParserCapabilities
from parsefabric.errors import ParseError
from parsefabric.models import JSONValue, ParseContext, ParsedEvent, ParseResult
from parsefabric.parser import Parser

_FRAME = re.compile(
    r'^\s*File "(?P<file>.+)", line (?P<line>\d+), in (?P<function>.+)$'
)
_EXCEPTION = re.compile(r"^(?P<exception_type>[\w.]+)(?:: (?P<message>.*))?$")


class PythonTracebackParser(Parser):
    """Extract the exception and stack frames from one Python traceback.

    The whole input is one ``python_exception`` event with
    ``exception_type``, ``message`` and ``frames`` (``file``, ``line``,
    ``function``) attributes. The exception is the last non-frame line that
    looks like ``ExceptionType: message``; the event's evidence spans the
    whole input.
    """

    @property
    @override
    def name(self) -> str:
        return "python-traceback"

    @property
    @override
    def version(self) -> str:
        return "1"

    @property
    @override
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(
            deterministic=True,
            parallel_safe=True,
            aggregatable=True,
        )

    @override
    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        """Parse one traceback.

        Args:
            source: Traceback text or UTF-8 bytes.
            context: Source description; ``source_offset`` shifts offsets.

        Returns:
            A result with one ``python_exception`` event.

        Raises:
            TypeError: If ``source`` is not text or bytes.
            ParseError: If no exception line is found or the text is not
                valid Unicode.
        """
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="strict")
        elif isinstance(source, str):
            text = source
        else:
            raise TypeError("traceback parser accepts only str or bytes")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ParseError("traceback text must be valid Unicode") from error

        frames: list[JSONValue] = []
        exception: re.Match[str] | None = None
        for line in text.splitlines():
            frame = _FRAME.match(line)
            if frame:
                frames.append(
                    {
                        "file": frame.group("file"),
                        "line": int(frame.group("line")),
                        "function": frame.group("function"),
                    }
                )
                continue
            stripped = line.strip()
            if stripped and not stripped.startswith("Traceback "):
                candidate = _EXCEPTION.match(stripped)
                if candidate:
                    exception = candidate
        if exception is None:
            raise ParseError("no Python exception summary found in traceback")
        start = context.source_offset if context and context.source_offset else 0
        event = self._with_parser_evidence(
            ParsedEvent(
                event_type="python_exception",
                severity="ERROR",
                attributes={
                    "exception_type": exception.group("exception_type"),
                    "message": exception.group("message") or "",
                    "frames": frames,
                },
            ),
            context,
            start_offset=start,
            end_offset=start + size,
            line_number=1,
        )
        return ParseResult(
            events=(event,),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
