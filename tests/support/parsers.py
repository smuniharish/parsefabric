"""Order-sensitive stateful parser used to exercise capability checks in tests."""

from __future__ import annotations

from parsefabric.capabilities import ParserCapabilities
from parsefabric.models import ParseContext, ParsedEvent, ParseResult
from parsefabric.parser import Parser


class StatefulSequenceParser(Parser):
    """Stateful parser whose order-sensitive capabilities block partitioning."""

    def __init__(self) -> None:
        self._previous: str | None = None

    @property
    def name(self) -> str:
        return "stateful-sequence"

    @property
    def version(self) -> str:
        return "1"

    @property
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(
            deterministic=True,
            incremental=True,
            stateful=True,
            requires_order=True,
        )

    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        if not isinstance(source, str):
            raise TypeError("stateful sequence parser accepts only str")
        event = self._with_parser_evidence(
            ParsedEvent(
                event_type="sequence_item",
                attributes={"value": source, "previous": self._previous},
            ),
            context,
        )
        self._previous = source
        return ParseResult(
            events=(event,),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
