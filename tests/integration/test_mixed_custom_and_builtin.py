"""Exercise mixed routing with a custom SQL parser and shipped parsers."""

from types import ModuleType

import mixed_custom_and_builtin
import pytest

from parsefabric.engine import ParseEngine
from parsefabric.errors import ParseError
from tests.support.grouped import rows


@pytest.fixture
def scenarios() -> ModuleType:
    return mixed_custom_and_builtin


@pytest.mark.parametrize(
    (
        "filename",
        "timestamped",
        "custom_log_format",
        "events",
        "sql_lines",
        "code_line",
    ),
    [
        ("mixed-shop-incident.txt", True, False, 26, [3, 4, 7, 8, 10, 13, 18, 21], 13),
        ("mixed-audit-review.txt", False, False, 20, [3, 4, 7, 8, 11, 14, 17], 11),
        ("mixed-custom-clock.txt", True, True, 15, [3, 4, 9, 11], 11),
    ],
)
async def test_mixed_custom_and_builtin_routes_in_both_modes(
    scenarios: ModuleType,
    filename: str,
    timestamped: bool,
    custom_log_format: bool,
    events: int,
    sql_lines: list[int],
    code_line: int,
) -> None:
    parser, result, source = await scenarios.parse_file(
        filename, timestamped=timestamped, custom_log_format=custom_log_format
    )
    assert len(result.events) == events
    assert not result.errors
    assert [
        event.evidence.line_number
        for event in result.events
        if event.evidence.parser_name == "sql-statements"
    ] == sql_lines
    assert {event.evidence.parser_name for event in result.events} == {
        "sql-statements",
        "json",
        "shop-metrics",
        "mixed-content",
        "timestamped-log" if timestamped else "application-log",
    }
    assert all(event.evidence.source_id == filename for event in result.events)
    data = source.encode("utf-8")
    for event in result.events:
        evidence = event.evidence
        assert evidence.start_offset is not None
        assert evidence.end_offset is not None
        assert 0 <= evidence.start_offset < evidence.end_offset <= len(data)
        if evidence.parser_name == "sql-statements":
            original = data[evidence.start_offset : evidence.end_offset].decode()
            assert original.strip().endswith(";")
            assert "raw_sql" not in event.attributes
    fenced_events = [
        event for event in result.events if event.evidence.line_number == code_line
    ]
    assert len(fenced_events) == 1
    assert fenced_events[0].event_type == "sql_statement"
    assert fenced_events[0].evidence.parser_name == "sql-statements"
    assert fenced_events[0].evidence.pattern_name == "code_fence:sql"
    fence_lines = (code_line - 1, code_line + 1)
    assert [
        (event.event_type, event.evidence.pattern_name)
        for event in result.events
        if event.evidence.line_number in fence_lines
    ] == [("fence", "code_fence")] * 2

    documents = await parser.aggregate(result.events)
    by_parser = {
        (document.event_type, document.parser_name): document for document in documents
    }
    assert len(by_parser) == len(documents)
    assert sum(document.count for document in documents) == events
    assert all(document.source_id == filename for document in documents)
    sql_document = by_parser["sql_statement", "sql-statements"]
    assert sql_document.count == len(sql_lines)
    sql_entries = rows(sql_document)
    assert sum(occurrences for *_, occurrences in sql_entries) == len(sql_lines)
    assert all(
        isinstance(message, str)
        and message.split(" ", 1)[0] in {"select", "insert", "update", "delete"}
        for _, message, _, _ in sql_entries
    )
    assert sql_entries[0][2] == f"{sql_lines[0]},{sql_lines[1]}"
    restored = await ParseEngine().materialize(parser, source, documents)
    assert restored == result.events
    assert restored[2].attributes["sql"] == result.events[2].attributes["sql"]

    first_sql = tuple(
        event for event in result.events if event.evidence.line_number in (3, 4)
    )
    (sql_only,) = await scenarios.SQLStatementParser().aggregate(first_sql)
    assert sql_only.count == 2
    assert [(refs, count) for _, _, refs, count in rows(sql_only)] == [("3,4", 2)]
    if custom_log_format:
        logs = [
            event
            for event in restored
            if event.evidence.parser_name == "timestamped-log"
        ]
        assert [event.attributes["message"] for event in logs] == [
            "inventory scan started",
            "inventory reader stalled",
            "inventory reader stalled",
            "inventory reader stalled",
            "backup reader restored",
        ]
        log_rows = rows(by_parser["log", "timestamped-log"])
        assert sum(count for *_, count in log_rows) == len(logs)
        assert ("ERROR", "inventory reader stalled") in {
            (severity, message) for severity, message, _, _ in log_rows
        }


async def test_mixed_route_propagates_sql_errors_and_preserves_invalid_json(
    scenarios: ModuleType,
) -> None:
    parser = scenarios.make_parser(timestamped=False)
    with pytest.raises(ParseError, match="invalid PostgreSQL"):
        await parser.parse("SELECT * FROM (")
    invalid = await parser.parse('{"bad": }')
    assert len(invalid.events) == 1
    assert invalid.events[0].event_type == "unparsed"
    assert invalid.events[0].attributes == {"text": '{"bad": }'}
    assert invalid.errors[0].error_type == "DecodeError"
    fenced = await parser.parse("```sql\nSELECT * FROM (\n```")
    assert [event.event_type for event in fenced.events] == ["fence", "code", "fence"]
