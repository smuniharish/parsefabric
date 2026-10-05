"""Exercise the external SQLGlot example against its real input document."""

import custom_sql
import pytest
from custom_sql import SQLStatementParser

from parsefabric.engine import ParseEngine
from parsefabric.errors import CapabilityError, ParseError
from parsefabric.models import ParseContext
from tests.support.grouped import rows
from tests.support.paths import EXAMPLE_DATA

_SOURCE = EXAMPLE_DATA / "shop-operations.sql"


async def test_sql_fixture_preserves_operations_order_tables_and_evidence() -> None:
    source = _SOURCE.read_text(encoding="utf-8")
    parser = SQLStatementParser()
    engine = ParseEngine()
    context = ParseContext(source_id=_SOURCE.name, source_offset=27)
    result = await engine.parse(parser, source, context)
    assert len(result.events) == 25
    assert [result.events[i].evidence.line_number for i in (0, 2, 8, 9, 24)] == [
        2,
        12,
        31,
        34,
        66,
    ]
    sql = result.events[8].attributes["sql"]
    assert isinstance(sql, str)
    assert sql.count("review; manual") == 1
    assert result.events[9].attributes["tables"] == [
        "shop.customers",
        "shop.orders",
    ]
    assert all(event.evidence.source_id == _SOURCE.name for event in result.events)
    for event in result.events:
        start = event.evidence.start_offset
        end = event.evidence.end_offset
        assert start is not None
        assert end is not None
        original = source.encode("utf-8")[start - 27 : end - 27].decode("utf-8")
        assert original.rstrip().endswith(";")
        # The offsets locate the original text; ``sql`` is its normalized form.
        assert (
            custom_sql.describe_statement(original.strip().removesuffix(";"))["sql"]
            == event.attributes["sql"]
        )
        assert "raw_sql" not in event.attributes

    (document,) = await engine.aggregate(parser, result.events)
    assert document.event_type == "sql_statement"
    assert (document.source_id, document.parser_name) == (
        _SOURCE.name,
        "sql-statements",
    )
    assert document.count == len(result.events)
    assert not document.retains_events
    (group,) = document.groups
    assert (group.pattern, group.severity) == (None, None)
    assert sum(entry.occurrences for entry in group.evidence) == 25
    assert len(group.evidence) < 25
    assert all(entry.events == () for entry in group.evidence)
    lines = [
        event.evidence.line_number
        for event in result.events
        if event.attributes["operation"] == "select"
    ]
    messages = {
        f"{event.attributes['operation']} "
        + ",".join(str(table) for table in event.attributes["tables"])  # type: ignore[union-attr]
        for event in result.events
    }
    assert {entry.message for entry in group.evidence} == messages
    assert group.evidence[0].message == "select shop.orders"
    assert group.evidence[0].positions[0] == lines[0]

    restored = await engine.materialize(parser, source, (document,), context)
    assert restored == result.events
    assert restored[8].attributes["sql"] == sql
    assert restored[9].attributes["tables"] == ["shop.customers", "shop.orders"]
    assert await parser.merge_aggregates((document,)) == (document,)
    with pytest.raises(CapabilityError, match="source documents"):
        await parser.merge_aggregates((document, document))


async def test_sql_input_and_aggregation_failures_are_explicit() -> None:
    parser = SQLStatementParser()
    with pytest.raises(TypeError, match="text or UTF-8"):
        await parser.parse(object())
    with pytest.raises(UnicodeDecodeError):
        await parser.parse(b"\xff")
    with pytest.raises(ParseError, match="invalid PostgreSQL statement"):
        await parser.parse("SELECT * FROM (")
    with pytest.raises(ParseError, match="invalid PostgreSQL statement"):
        await parser.parse("SELECT FROM;")
    with pytest.raises(ParseError, match="unsupported SQL statement"):
        await parser.parse("CREATE TABLE t (id INT);")

    assert (await parser.parse("-- comments only")).events == ()
    result = await parser.parse(
        "SELECT 'a;b' AS label;\nSELECT 'c' AS label;",
        ParseContext(source_id="one.sql"),
    )
    assert len(result.events) == 2
    assert result.events[0].attributes["sql"] == "SELECT 'a;b' AS label"
    assert result.events[1].evidence.line_number == 2
    with pytest.raises(ValueError, match="source order"):
        await parser.aggregate(reversed(result.events))
    other = (await parser.parse("SELECT 3;", ParseContext(source_id="two.sql"))).events
    with pytest.raises(ValueError, match="source document"):
        await parser.aggregate((*result.events, *other))
    unicode_result = await parser.parse(
        "SELECT 'café; open' AS label;\nSELECT 2;", ParseContext(source_offset=13)
    )
    assert unicode_result.events[0].evidence.end_offset == 13 + len(
        "SELECT 'café; open' AS label;".encode()
    )
    assert unicode_result.events[1].evidence.start_offset == 13 + len(
        "SELECT 'café; open' AS label;".encode()
    )


async def test_sql_package_aggregation_accepts_async_event_stream() -> None:
    parser = SQLStatementParser()
    result = await parser.parse("SELECT 1;\nSELECT 2;")

    async def events():
        for event in result.events:
            yield event

    (document,) = await parser.aggregate(events())
    assert document.count == 2
    assert [(refs, count) for *_, refs, count in rows(document)] == [("1,2", 2)]


async def test_repeated_sql_references_round_trip_queries() -> None:
    source = (
        "SELECT id, total_cents FROM shop.orders WHERE status = 'pending';\n"
        "SELECT id, total_cents FROM shop.orders WHERE status = 'pending';"
    )
    parser = SQLStatementParser()
    engine = ParseEngine()
    context = ParseContext(source_id="shop.sql")
    result = await engine.parse(parser, source, context)
    (document,) = await engine.aggregate(parser, result.events)
    select = "select shop.orders"
    assert rows(document) == [(None, select, "1,2", 2)]
    restored = await engine.materialize(parser, source, (document,), context)
    expected_query = "SELECT id, total_cents FROM shop.orders WHERE status = 'pending'"
    assert [event.attributes["sql"] for event in restored] == [expected_query] * 2

    separated = (
        source
        + "\nUPDATE shop.orders SET status = 'processing' WHERE id = 4101;\n"
        + source.splitlines()[0]
    )
    ordered = await parser.parse(separated, ParseContext(source_id="shop.sql"))
    (aggregate,) = await parser.aggregate(ordered.events)
    update = "update shop.orders"
    assert rows(aggregate) == [
        (None, select, "1,2", 2),
        (None, update, "3", 1),
        (None, select, "4", 1),
    ]
    assert [event.attributes["operation"] for event in ordered.events] == [
        "select",
        "select",
        "update",
        "select",
    ]


def test_describe_statement_normalizes_operation_tables_and_sql() -> None:
    described = custom_sql.describe_statement(
        "SELECT o.id, o.total_cents FROM shop.orders AS o "
        "WHERE o.status = 'pending' ORDER BY o.id"
    )
    assert described == {
        "message": "select shop.orders",
        "operation": "select",
        "tables": ["shop.orders"],
        "sql": "SELECT o.id, o.total_cents FROM shop.orders AS o "
        "WHERE o.status = 'pending' ORDER BY o.id",
    }
    with pytest.raises(ParseError, match="unsupported SQL statement"):
        custom_sql.describe_statement("CREATE TABLE t (id INT)")


async def test_sql_materialize_round_trips_fixture_and_edge_sources() -> None:
    engine = ParseEngine()
    sources = (
        (_SOURCE.read_text(encoding="utf-8"), _SOURCE.name),
        ("SELECT 'a;b' FROM t;\n\nUPDATE t SET x = 1\n  WHERE id = 2\n", "edge.sql"),
    )
    for source, source_id in sources:
        parser = SQLStatementParser()
        context = ParseContext(source_id=source_id)
        result = await engine.parse(parser, source, context)
        (document,) = await engine.aggregate(parser, result.events)
        restored = await engine.materialize(parser, source, (document,), context)
        assert restored == result.events
        assert [event.attributes["sql"] for event in restored] == [
            event.attributes["sql"] for event in result.events
        ]
        assert sum(entry.occurrences for entry in document.groups[0].evidence) == len(
            result.events
        )
