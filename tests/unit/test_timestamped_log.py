import re
from collections.abc import Callable

import pytest

from parsefabric.builtins import (
    ApplicationLogParser,
    MixedContentParser,
    TimestampedLogParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import CapabilityError, ParseError
from parsefabric.models import ParseContext
from parsefabric.patterns import RegexPattern
from tests.support.grouped import rows

SOURCE = "\n".join(
    [
        "2026-10-10T10:10:10+00:00 INFO started",
        "2026-10-10T10:10:11+00:00 INFO started",
        "2026-10-10T10:10:12+00:00 DEBUG checking",
        "2026-10-10T10:10:13+00:00 DEBUG checking",
        "2026-10-10T10:10:14+00:00 INFO started",
        "2026-10-10T10:10:15+00:00 INFO started",
        "2026-10-10T10:10:16+00:00 ERROR timeout",
        "2026-10-10T10:10:17+00:00 ERROR timeout",
        "2026-10-10T10:10:18+00:00 INFO started",
        "2026-10-10T10:10:19+00:00 ERROR timeout",
    ]
)


async def test_dependent_log_runs_group_by_level_and_keep_timestamps() -> None:
    parser = TimestampedLogParser()
    context = ParseContext(source_id="app.log", source_offset=9)
    engine = ParseEngine()
    result = await engine.parse(parser, SOURCE, context)
    (document,) = await engine.aggregate(parser, result.events)
    assert document.event_type == "log"
    assert document.count == 10
    assert (document.source_id, document.parser_name) == ("app.log", "timestamped-log")
    assert rows(document) == [
        ("INFO", "started", "1,2", 2),
        ("INFO", "started", "5,6", 2),
        ("INFO", "started", "9", 1),
        ("DEBUG", "checking", "3,4", 2),
        ("ERROR", "timeout", "7,8", 2),
        ("ERROR", "timeout", "10", 1),
    ]
    assert document.first_seen is not None
    assert document.last_seen is not None
    assert document.first_seen.isoformat() == "2026-10-10T10:10:10+00:00"
    assert document.last_seen.isoformat() == "2026-10-10T10:10:19+00:00"
    assert result.events[6].evidence.line_number == 7
    assert result.events[0].evidence.start_offset == 9
    restored = await engine.materialize(parser, SOURCE, (document,), context)
    assert restored == result.events
    assert restored[6].attributes["message"] == "timeout"
    assert not parser.capabilities.partitionable


async def test_dependent_log_references_round_trip_event_attributes() -> None:
    source = (
        "2026-09-30T10:15:00+00:00 ERROR api database timeout on node-01\n"
        "2026-09-30T10:15:02+00:00 ERROR api database timeout on node-01"
    )
    parser = TimestampedLogParser()
    context = ParseContext(source_id="incident-mixed.log")
    result = await parser.parse(source, context)
    (document,) = await parser.aggregate(result.events)
    assert rows(document) == [("ERROR", "api database timeout on node-01", "1,2", 2)]
    assert all("raw_message" not in event.attributes for event in result.events)
    assert [
        source.encode()[event.evidence.start_offset : event.evidence.end_offset]
        .decode()
        .rstrip("\n")
        for event in result.events
    ] == source.splitlines()
    restored = await ParseEngine().materialize(parser, source, (document,), context)
    assert restored == result.events
    assert [event.attributes["message"] for event in restored] == [
        "api database timeout on node-01",
        "api database timeout on node-01",
    ]
    repeated = "\n".join([source.splitlines()[0]] * 20)
    repeated_events = (await parser.parse(repeated)).events
    (compressed,) = await parser.aggregate(repeated_events)
    assert rows(compressed) == [
        (
            "ERROR",
            "api database timeout on node-01",
            "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20",
            20,
        )
    ]


async def test_large_mixed_fixture_routes_logs_into_one_grouped_aggregate(
    example_data: Callable[[str], str],
) -> None:
    source = example_data("incident-mixed.log")
    log_parser = TimestampedLogParser()
    mixed = MixedContentParser(
        routes=[(RegexPattern("log-line", r"^\d{4}-"), log_parser)]
    )
    result = await ParseEngine().parse(
        mixed, source, ParseContext(source_id="incident-mixed.log")
    )
    logs = tuple(
        event
        for event in result.events
        if event.evidence.parser_name == log_parser.name
    )
    (document,) = await ParseEngine().aggregate(log_parser, logs)
    assert document.count == 510
    assert (document.source_id, document.parser_name) == (
        "incident-mixed.log",
        "timestamped-log",
    )
    entries = rows(document)
    assert sum(occurrences for *_, occurrences in entries) == 510
    errors = [entry for entry in entries if entry[0] == "ERROR"]
    assert errors
    assert any(occurrences >= 2 for *_, occurrences in errors)
    assert len(entries) < 510


async def test_filtered_logs_split_runs_at_source_gaps() -> None:
    logs = TimestampedLogParser()
    mixed = MixedContentParser(routes=[(RegexPattern("log-line", r"^\d{4}-"), logs)])
    source = (
        "2026-10-10T10:10:10+00:00 ERROR timeout\n"
        "operator note\n"
        "2026-10-10T10:10:11+00:00 ERROR timeout"
    )
    result = await mixed.parse(source, ParseContext(source_id="incident.log"))
    (document,) = await logs.aggregate(
        event for event in result.events if event.evidence.parser_name == logs.name
    )
    # The unrouted note between them breaks the run.
    assert rows(document) == [
        ("ERROR", "timeout", "1", 1),
        ("ERROR", "timeout", "3", 1),
    ]
    assert document.count == 2


async def test_ordered_logs_validate_format_order_and_merge_boundary() -> None:
    parser = TimestampedLogParser()
    with pytest.raises(ParseError, match="line 2"):
        await parser.parse("2026-10-10T10:10:10+00:00 INFO ok\nnot a log")
    with pytest.raises(ParseError, match="timezone"):
        await parser.parse("2026-10-10T10:10:10 INFO ok")
    unordered = tuple(reversed((await parser.parse(SOURCE)).events))
    with pytest.raises(ValueError, match="source order"):
        await parser.aggregate(unordered)
    (partial,) = await parser.aggregate((await parser.parse(SOURCE)).events)
    assert await parser.merge_aggregates([partial]) == (partial,)
    with pytest.raises(CapabilityError, match="source documents"):
        await parser.merge_aggregates([partial, partial])


async def test_custom_log_format_is_configurable_in_mixed_routes() -> None:
    pattern = re.compile(r"^\[(?P<at>[^\]]+)\] \[(?P<level>[A-Z]+)\] (?P<message>.+)$")
    logs = TimestampedLogParser(line_pattern=pattern)
    source = (
        "[2026-10-01T08:00:00+00:00] [ERROR] queue lag\n"
        "[2026-10-01T08:00:01+00:00] [ERROR] queue lag\n"
        '{"state":"investigating"}\n'
        "[2026-10-01T08:00:02+00:00] [ERROR] queue lag"
    )
    with pytest.raises(ParseError, match="line 1"):
        await TimestampedLogParser().parse(source.splitlines()[0])
    mixed = MixedContentParser(routes=[(RegexPattern("custom-log", r"^\["), logs)])
    context = ParseContext(source_id="custom.log")
    result = await mixed.parse(source, context)
    assert [event.evidence.line_number for event in result.events] == [1, 2, 3, 4]
    assert [event.attributes.get("message") for event in result.events] == [
        "queue lag",
        "queue lag",
        None,
        "queue lag",
    ]
    documents = await mixed.aggregate(result.events)
    assert [(document.event_type, rows(document)) for document in documents] == [
        ("log", [("ERROR", "queue lag", "1,2", 2), ("ERROR", "queue lag", "4", 1)]),
        ("other", [(None, {"text": '{"state":"investigating"}'}, "3", 1)]),
    ]
    restored = await ParseEngine().materialize(mixed, source, documents, context)
    assert restored == result.events
    assert [
        event.attributes["message"]
        for event in restored
        if "message" in event.attributes
    ] == [
        "queue lag",
        "queue lag",
        "queue lag",
    ]
    (logs_document,) = await logs.aggregate(
        event for event in result.events if event.evidence.parser_name == logs.name
    )
    assert rows(logs_document) == [
        ("ERROR", "queue lag", "1,2", 2),
        ("ERROR", "queue lag", "4", 1),
    ]
    assert isinstance(
        TimestampedLogParser(line_pattern=pattern.pattern), TimestampedLogParser
    )


def test_custom_log_format_rejects_incomplete_or_non_text_patterns() -> None:
    with pytest.raises(ValueError, match="at, level, and message"):
        TimestampedLogParser(line_pattern=r"(?P<message>.+)")
    with pytest.raises(TypeError, match="line_pattern"):
        TimestampedLogParser(line_pattern=3)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="text regex"):
        TimestampedLogParser(
            line_pattern=re.compile(b"(?P<at>x)(?P<level>x)(?P<message>x)")  # type: ignore[arg-type]
        )  # type: ignore[arg-type]


async def test_builtin_pattern_collections_can_override_log_recognition() -> None:
    fallback = MixedContentParser(
        patterns=[
            RegexPattern(
                "bracketed",
                r"^\[[^\]]+\] \[(?P<level>[A-Z]+)\] (?P<message>.+)$",
                event_type="log",
            )
        ]
    )
    source = (
        "[2026-10-01T08:00:00+00:00] [ERROR] queue lag\n"
        "[2026-10-01T08:00:01+00:00] [ERROR] queue lag"
    )
    result = await fallback.parse(source)
    (document,) = await fallback.aggregate(result.events)
    assert rows(document) == [(None, "queue lag", "1,2", 2)]
    assert document.groups[0].pattern == "bracketed"

    application = ApplicationLogParser(
        patterns=[
            RegexPattern(
                "queue", r"^QUEUE (?P<message>.+)$", event_type="queue_warning"
            )
        ]
    )
    events = (await application.parse("QUEUE delayed")).events
    assert [(event.event_type, event.attributes) for event in events] == [
        ("queue_warning", {"message": "delayed"})
    ]  # type: ignore[arg-type]
