"""Write a custom SQL statement parser with SQLGlot and aggregate it losslessly.

Requires sqlglot (``pip install sqlglot``, or ``uv sync`` in a checkout).
Nothing in this example connects to a database or executes SQL.

Run: python examples/custom_sql.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import sqlglot
from sqlglot import ErrorLevel, exp
from sqlglot.errors import ParseError as SQLGlotParseError
from sqlglot.errors import TokenError
from sqlglot.tokens import Tokenizer, TokenType

from parsefabric.capabilities import ParserCapabilities
from parsefabric.compression import measure_compression
from parsefabric.engine import ParseEngine
from parsefabric.errors import ParseError
from parsefabric.models import JSONValue, ParseContext, ParsedEvent, ParseResult
from parsefabric.parser import Parser

DATA = Path(__file__).resolve().parent / "data"
_DIALECT = "postgres"
_OPERATIONS = {
    exp.Select: "select",
    exp.Insert: "insert",
    exp.Update: "update",
    exp.Delete: "delete",
}


def describe_statement(statement: str) -> dict[str, JSONValue]:
    """Return the evidence message, operation, physical tables, and normalized SQL."""
    tree = sqlglot.parse_one(statement, read=_DIALECT, error_level=ErrorLevel.IMMEDIATE)
    if tree is None:
        raise ParseError("expected a SQL statement")
    operation = next(
        (name for kind, name in _OPERATIONS.items() if isinstance(tree, kind)),
        None,
    )
    if operation is None:
        raise ParseError(f"unsupported SQL statement: {type(tree).__name__}")
    cte_names = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    tables: list[str] = []
    for table in tree.find_all(exp.Table):
        if table.name in cte_names and not table.db:
            continue
        physical = table.copy()
        physical.set("alias", None)
        table_name = physical.sql(dialect=_DIALECT)
        if table_name not in tables:
            tables.append(table_name)
    return {
        # The evidence identity: statements on the same tables share an entry.
        "message": f"{operation} {','.join(tables)}".rstrip(),
        "operation": operation,
        "tables": list[JSONValue](tables),
        "sql": tree.sql(dialect=_DIALECT, comments=False),
    }


class SQLStatementParser(Parser):
    """Only ``parse`` is written; ParseFabric aggregates the SQL evidence.

    Each event's ``message`` (operation and tables) is its evidence identity;
    line positions locate every statement, so the SQL itself is never copied.
    ``sql`` is the normalized statement; the original text is the source slice
    at the event's byte offsets, so it is not stored again.
    """

    @property
    def name(self) -> str:
        return "sql-statements"

    @property
    def version(self) -> str:
        return "1"

    @property
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(
            deterministic=True, parallel_safe=True, aggregatable=True
        )

    async def parse(
        self, source: object, context: ParseContext | None = None
    ) -> ParseResult:
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="strict")
        elif isinstance(source, str):
            text = source
        else:
            raise TypeError("SQL input must be text or UTF-8 bytes")

        try:
            tokens = Tokenizer(dialect=_DIALECT).tokenize(text)
        except TokenError as error:
            raise ParseError("invalid PostgreSQL token in SQL input") from error
        events: list[ParsedEvent] = []
        offset = context.source_offset if context else None
        start = 0
        byte_start = 0

        def add_statement(end: int, first_token_start: int) -> None:
            statement = text[start:end]
            if not statement.strip():
                return
            try:
                described = describe_statement(statement)
            except SQLGlotParseError as error:
                line = text.count("\n", 0, first_token_start) + 1
                raise ParseError(
                    f"invalid PostgreSQL statement at line {line}"
                ) from error
            line_number = text.count("\n", 0, first_token_start) + 1
            event = ParsedEvent(
                "sql_statement",
                attributes={
                    "message": described["message"],
                    "operation": described["operation"],
                    "tables": described["tables"],
                    "line_span": text.count("\n", first_token_start, end) + 1,
                    "sql": described["sql"],
                },
            )
            events.append(
                self._with_parser_evidence(
                    event,
                    context,
                    start_offset=(offset or 0) + byte_start,
                    end_offset=(offset or 0)
                    + byte_start
                    + len(statement.encode("utf-8")),
                    line_number=line_number,
                )
            )

        first_token_start: int | None = None
        for token in tokens:
            if token.token_type == TokenType.SEMICOLON:
                if first_token_start is not None:
                    add_statement(token.end + 1, first_token_start)
                byte_start += len(text[start : token.end + 1].encode("utf-8"))
                start = token.end + 1
                first_token_start = None
            elif first_token_start is None:
                first_token_start = token.start
        if first_token_start is not None:
            add_statement(len(text), first_token_start)
        return ParseResult(
            events=tuple(events),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )


async def main() -> None:
    source = await asyncio.to_thread(
        (DATA / "shop-operations.sql").read_text, encoding="utf-8"
    )
    engine = ParseEngine()
    context = ParseContext(source_id="shop-operations.sql")
    parser = SQLStatementParser()
    result = await engine.parse(parser, source, context)
    (document,) = await engine.aggregate(parser, result.events)
    print("input lines:", len(source.splitlines()), "statements:", len(result.events))
    print("aggregate:", document.event_type, "count:", document.count)
    for group in document.groups:
        for entry in group.evidence:
            print(" ", entry.occurrences, "x", list(entry.positions), entry.message)
    # The parser owns the wire format; measure the compact document it stores.
    metrics = measure_compression(source, parser.serialize((document,)))
    print(
        "bytes:",
        metrics.input_bytes,
        "->",
        metrics.output_bytes,
        f"({metrics.reduction_percent:.1f}% smaller)",
    )
    restored = await engine.materialize(parser, source, (document,))
    print("materialized:", len(restored), "lossless:", restored == result.events)
    for index, event in enumerate(restored, start=1):
        print(
            " statement:",
            index,
            event.attributes["operation"],
            event.attributes["tables"],
            "line:",
            event.evidence.line_number,
            "sql:",
            event.attributes["sql"],
        )


if __name__ == "__main__":
    asyncio.run(main())
