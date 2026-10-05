"""JSON document parser with explicit invalid-input results.

Decoding uses msgspec: it is strict RFC 8259 (``NaN`` and out-of-range numbers
such as ``1e400`` are invalid) and keeps integers of any size exact.
"""

from __future__ import annotations

from typing import Any, override

import msgspec

from parsefabric._json import MAX_JSON_DEPTH, copy_json
from parsefabric.capabilities import ParserCapabilities
from parsefabric.errors import ParseError, ParseIssue
from parsefabric.models import ParseContext, ParsedEvent, ParseResult
from parsefabric.parser import Parser


def _decode(text: str) -> Any:
    try:
        value = msgspec.json.decode(text)
    except RecursionError as error:
        raise ParseError(
            f"JSON document nests deeper than {MAX_JSON_DEPTH} levels"
        ) from error
    try:
        return copy_json(value, "JSON document")
    except ValueError as error:
        raise ParseError(str(error)) from error


class JSONParser(Parser):
    """Parse one JSON document, or an already-decoded JSON value, into one event.

    Text and bytes produce a ``json_record`` event whose ``value`` attribute
    is the decoded document and whose evidence spans the whole input. Invalid
    JSON is not raised: the result holds an ``unparsed`` event with the text
    and a `ParseIssue`. Values nested deeper than
    `parsefabric.MAX_JSON_DEPTH` levels are invalid.
    """

    @property
    @override
    def name(self) -> str:
        return "json"

    @property
    @override
    def version(self) -> str:
        return "1"

    @property
    @override
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(
            deterministic=True,
            incremental=True,
            parallel_safe=True,
            aggregatable=True,
        )

    @override
    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        """Parse JSON text, UTF-8 bytes, or an already-decoded JSON value.

        Args:
            source: JSON text or bytes, or a decoded JSON value.
            context: Source description; ``source_offset`` shifts offsets.

        Returns:
            A result with one ``json_record`` event, or one ``unparsed`` event
            and an issue for invalid JSON text.

        Raises:
            ParseError: If text is not valid Unicode or a decoded value is not
                JSON-compatible.
            UnicodeDecodeError: If bytes are not valid UTF-8.
        """
        start_offset = None
        end_offset = None
        line_number = None
        if isinstance(source, (str, bytes)):
            text = (
                source.decode("utf-8", errors="strict")
                if isinstance(source, bytes)
                else source
            )
            try:
                size = len(text.encode("utf-8"))
            except UnicodeEncodeError as error:
                raise ParseError("JSON text must be valid Unicode") from error
            start_offset = (
                context.source_offset if context and context.source_offset else 0
            )
            end_offset = start_offset + size
            line_number = 1
            try:
                value = _decode(text)
            except (msgspec.DecodeError, ParseError) as error:
                event = self._with_parser_evidence(
                    ParsedEvent("unparsed", attributes={"text": text}),
                    context,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    line_number=line_number,
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
        else:
            try:
                value = copy_json(source, "JSON input")
            except ValueError as error:
                raise ParseError("input is not a JSON-compatible value") from error
        event = self._with_parser_evidence(
            ParsedEvent(event_type="json_record", attributes={"value": value}),
            context,
            start_offset=start_offset,
            end_offset=end_offset,
            line_number=line_number,
        )
        return ParseResult(
            events=(event,),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
