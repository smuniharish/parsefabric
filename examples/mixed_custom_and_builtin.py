"""Compose a custom SQLGlot parser with built-in parsers over three mixed files.

SQL routes handle complete lines; routed JSON objects may span multiple lines.
Requires sqlglot (``pip install sqlglot``, or ``uv sync`` in a checkout).

Run: python examples/mixed_custom_and_builtin.py
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from custom_sql import SQLStatementParser

from parsefabric.aggregation import EvidenceAggregate
from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    MixedContentParser,
    TimestampedLogParser,
)
from parsefabric.compression import measure_compression
from parsefabric.engine import ParseEngine
from parsefabric.models import ParseContext, ParseResult
from parsefabric.patterns import RegexPattern

_DATA = Path(__file__).resolve().parent / "data"
_BRACKETED_LOG = r"^\[(?P<at>[^\]]+)\] \[(?P<level>[A-Z]+)\] (?P<message>.+)$"


def make_parser(
    *,
    timestamped: bool,
    custom_log_format: bool = False,
) -> MixedContentParser:
    if custom_log_format and not timestamped:
        raise ValueError("custom log format requires timestamped logs")
    logs = (
        TimestampedLogParser(
            line_pattern=_BRACKETED_LOG if custom_log_format else None,
        )
        if timestamped
        else ApplicationLogParser()
    )
    if custom_log_format:
        log_selector = r"^\["
    elif timestamped:
        log_selector = r"^\d{4}-\d\d-\d\dT\S+\s+"
    else:
        log_selector = r"^(?:WARN|ERROR)\b"
    metrics = CLIOutputParser(
        [
            RegexPattern(
                "measurement",
                r"^METRIC (?P<name>[a-z_]+): (?P<value>\d+)$",
                event_type="metric",
            )
        ],
        name="shop-metrics",
    )
    sql = SQLStatementParser()
    # Each routed parser's events are aggregated under that parser's name.
    return MixedContentParser(
        # ```sql fences are parsed as SQL; other fences stay code.
        fence_routes={"sql": sql},
        routes=[
            (RegexPattern("log-route", log_selector), logs),
            (
                RegexPattern(
                    "sql-route",
                    r"^(?:SELECT|UPDATE|INSERT|DELETE|WITH)\b",
                    flags=re.IGNORECASE,
                ),
                sql,
            ),
            (RegexPattern("json-route", r"^\{"), JSONParser()),
            (RegexPattern("metric-route", r"^METRIC\b"), metrics),
        ],
    )


def print_groups(documents: tuple[EvidenceAggregate, ...]) -> None:
    for document in documents:
        print(
            " aggregate:",
            document.event_type,
            document.parser_name,
            "count:",
            document.count,
        )
        for group in document.groups:
            for entry in group.evidence:
                print(
                    "   ",
                    group.severity,
                    entry.message,
                    "positions:",
                    list(entry.positions),
                    "occurrences:",
                    entry.occurrences,
                )


async def parse_file(
    filename: str, *, timestamped: bool, custom_log_format: bool = False
) -> tuple[MixedContentParser, ParseResult, str]:
    source = (_DATA / filename).read_text(encoding="utf-8")
    parser = make_parser(timestamped=timestamped, custom_log_format=custom_log_format)
    result = await ParseEngine().parse(parser, source, ParseContext(source_id=filename))
    return parser, result, source


async def report(
    filename: str, *, timestamped: bool, custom_log_format: bool = False
) -> None:
    parser, result, source = await parse_file(
        filename, timestamped=timestamped, custom_log_format=custom_log_format
    )
    engine = ParseEngine()
    documents = await engine.aggregate(parser, result.events)
    print(filename, "lines:", len(source.splitlines()), "events:", len(result.events))
    print(
        "parsers:",
        sorted(
            name
            for name in {event.evidence.parser_name for event in result.events}
            if name is not None
        ),
    )
    print("aggregates:", len(documents))
    print_groups(documents)
    metrics = measure_compression(source, parser.serialize(documents))
    print("bytes:", metrics.input_bytes, "->", metrics.output_bytes)
    restored = await engine.materialize(parser, source, documents)
    print("lossless:", restored == result.events)
    sql_events = tuple(
        event
        for event in result.events
        if event.evidence.parser_name == "sql-statements"
    )
    print(
        "SQL event lines:",
        [event.evidence.line_number for event in sql_events],
    )
    print(
        "first SQL:",
        sql_events[0].attributes["operation"],
        sql_events[0].attributes["tables"],
        "line:",
        sql_events[0].evidence.line_number,
    )
    print(
        "fenced SQL lines:",
        [
            event.evidence.line_number
            for event in sql_events
            if event.evidence.pattern_name == "code_fence:sql"
        ],
    )
    print(
        "JSON values:",
        [
            event.attributes["value"]
            for event in result.events
            if event.evidence.parser_name == "json"
        ],
    )
    print(
        "metric values:",
        [
            event.attributes
            for event in result.events
            if event.evidence.parser_name == "shop-metrics"
        ],
    )

    # A child parser aggregates only its own events.
    sql_documents = await engine.aggregate(SQLStatementParser(), sql_events)
    print("custom SQL aggregator:")
    print_groups(sql_documents)
    print()


async def main() -> None:
    await report("mixed-shop-incident.txt", timestamped=True)
    await report("mixed-audit-review.txt", timestamped=False)
    await report("mixed-custom-clock.txt", timestamped=True, custom_log_format=True)


if __name__ == "__main__":
    asyncio.run(main())
