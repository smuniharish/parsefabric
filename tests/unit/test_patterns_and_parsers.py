import pytest

from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    PythonTracebackParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import CapabilityError, ParseError
from parsefabric.models import ParseContext
from parsefabric.partitioning import LinePartitioner
from parsefabric.patterns import (
    ExactPattern,
    PredicatePattern,
    RegexPattern,
    StructuredPattern,
)
from tests.support.parsers import StatefulSequenceParser


def test_pattern_kinds_are_independently_composable() -> None:
    regex_match = RegexPattern("r", r"(?P<id>\d+)").match("id=12")
    assert regex_match is not None
    assert regex_match.attributes == {"id": "12"}
    empty_capture = RegexPattern("empty", r"(?P<value>.*)").match("")
    assert empty_capture is not None
    assert empty_capture.attributes == {"value": ""}
    assert ExactPattern("exact", "ready").match("ready") is not None
    assert PredicatePattern("predicate", lambda value: value == 2).match(2)
    structured = StructuredPattern("structured", lambda value: value.get("ok") is True)
    assert structured.match({"ok": True})
    assert structured.match("not a mapping") is None


async def test_application_parser_supports_multiple_patterns_and_evidence() -> None:
    parser = ApplicationLogParser()
    result = await ParseEngine().parse(
        parser,
        "database timeout; connection refused",
        ParseContext(source_id="service.log", correlation_id="trace-1"),
    )
    assert {event.event_type for event in result.events} == {
        "timeout",
        "connection_failure",
    }
    assert all(event.evidence.source_id == "service.log" for event in result.events)
    assert all(
        event.evidence.parser_name == "application-log" for event in result.events
    )
    assert len(parser.patterns) >= 9
    assert sum(item.matches for item in result.pattern_statistics) == len(result.events)


async def test_source_offset_is_preserved_in_pattern_evidence() -> None:
    result = await ParseEngine().parse(
        ApplicationLogParser(),
        "timeout",
        ParseContext(source_id="chunked", source_offset=200),
    )
    assert result.events[0].evidence.start_offset == 200
    assert result.events[0].evidence.end_offset == 207


async def test_deterministic_parser_handles_line_boundaries_without_materializing_lines() -> (  # noqa: E501
    None
):
    parser = CLIOutputParser([RegexPattern("x", r"x")])
    result = await parser.parse("x\r\nx\x85x")
    assert [event.evidence.line_number for event in result.events] == [1, 2, 3]
    assert [
        (event.evidence.start_offset, event.evidence.end_offset)
        for event in result.events
    ] == [(0, 3), (3, 6), (6, 7)]


async def test_json_parser_and_invalid_json() -> None:
    result = await JSONParser().parse('{"status":"ok"}')
    assert result.events[0].attributes["value"] == {"status": "ok"}
    assert result.events[0].evidence.parser_name == "json"
    with pytest.raises(CapabilityError, match="capabilities"):
        tuple(
            LinePartitioner().partition(
                ['{"status":', '"ok"}'],
                capabilities=JSONParser().capabilities,
            )
        )
    original = "INFO private one\nINFO private two"
    invalid = await JSONParser().parse(original, ParseContext(source_id="raw.txt"))
    assert len(invalid.events) == 1
    assert invalid.events[0].event_type == "unparsed"
    assert invalid.events[0].attributes == {"text": original}
    assert invalid.events[0].evidence.source_id == "raw.txt"
    assert invalid.events[0].evidence.parser_name == "json"
    assert invalid.errors[0].error_type == "DecodeError"
    assert invalid.errors[0].source_id == "raw.txt"
    assert invalid.events[0].evidence.start_offset == 0
    assert invalid.events[0].evidence.end_offset == len(original.encode("utf-8"))
    assert invalid.events[0].evidence.line_number == 1
    (document,) = await JSONParser().aggregate(invalid.events)
    (group,) = document.groups
    assert [(entry.message, entry.occurrences) for entry in group.evidence] == [
        ({"text": original}, 1)
    ]
    assert not document.retains_events
    restored = await ParseEngine().materialize(JSONParser(), original, (document,))
    assert restored == invalid.events
    assert restored[0].attributes == {"text": original}

    offset = ParseContext(source_id="bytes.txt", source_offset=10)
    raw_bytes = b'{"status":'
    invalid_bytes = await JSONParser().parse(raw_bytes, offset)
    assert invalid_bytes.events[0].attributes == {"text": raw_bytes.decode()}
    assert invalid_bytes.events[0].evidence.start_offset == 10
    assert invalid_bytes.events[0].evidence.end_offset == 10 + len(raw_bytes)
    assert invalid_bytes.errors[0].error_type == "DecodeError"

    unsupported = await JSONParser().parse("NaN")
    assert unsupported.events[0].attributes == {"text": "NaN"}
    assert unsupported.errors[0].error_type == "DecodeError"
    with pytest.raises(UnicodeDecodeError):
        await JSONParser().parse(b"\xff")
    with pytest.raises(ParseError, match="JSON-compatible"):
        await JSONParser().parse(object())


async def test_traceback_parser_extracts_exception_frames() -> None:
    text = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 7, in run\n'
        "ValueError: invalid"
    )
    event = (await PythonTracebackParser().parse(text)).events[0]
    assert event.attributes["exception_type"] == "ValueError"
    assert event.attributes["frames"] == [
        {"file": "app.py", "line": 7, "function": "run"}
    ]


async def test_custom_cli_parser_and_stateful_capabilities() -> None:
    parser = CLIOutputParser([ExactPattern("ok", "done")])
    assert (await parser.parse("done")).events[0].event_type == "ok"
    stateful = StatefulSequenceParser()
    assert (await stateful.parse("first")).events[0].attributes["previous"] is None
    assert (await stateful.parse("second")).events[0].attributes["previous"] == "first"
    with pytest.raises(CapabilityError, match="capabilities"):
        tuple(LinePartitioner().partition(["a"], capabilities=stateful.capabilities))


def test_pattern_registration_is_ordered_and_replacement_is_controlled() -> None:
    parser = CLIOutputParser([ExactPattern("first", "a", priority=1)])
    parser.register_pattern(ExactPattern("second", "b", priority=4))
    assert [pattern.name for pattern in parser.patterns] == ["second", "first"]
    with pytest.raises(ValueError, match="already registered"):
        parser.register_pattern(ExactPattern("first", "c"))
    parser.register_pattern(ExactPattern("first", "c"), replace=True)
    assert parser.unregister_pattern("second").name == "second"
