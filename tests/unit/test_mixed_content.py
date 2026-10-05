from collections.abc import Callable

import pytest

from parsefabric.aggregation import Aggregate
from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    MixedContentParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import CapabilityError
from parsefabric.models import ParseContext
from parsefabric.partitioning import LinePartitioner
from parsefabric.patterns import PredicatePattern, RegexPattern
from parsefabric.serialization import dumps_result, loads_result
from tests.support.grouped import rows


def _summary(
    documents: tuple[Aggregate, ...], source: str
) -> list[tuple[str, str, int]]:
    """``(event_type, line refs, occurrences)`` per entry across aggregates."""
    return [
        (document.event_type, refs, occurrences)
        for document in documents
        for _, _, refs, occurrences in rows(document)
    ]


async def test_synthetic_incident_log_preserves_all_events_and_evidence(
    example_data: Callable[[str], str],
) -> None:
    source = example_data("incident-mixed.log")
    parser = MixedContentParser()
    engine = ParseEngine()
    result = await engine.parse(parser, source, ParseContext(source_id="incident.txt"))
    assert len(source.splitlines()) == len(result.events) == 1254
    assert [event.evidence.line_number for event in result.events] == list(
        range(1, 1255)
    )
    assert result.events[1].attributes == {
        "text": "request_id=req-4100 route=/v1/api/items"
    }
    assert [result.events[index].event_type for index in (5, 6, 9)] == [
        "log",
        "log",
        "fence",
    ]
    assert result.events[9].evidence.pattern_name == "code_fence"
    assert result.events[-1].evidence.end_offset == len(source.encode("utf-8"))
    assert all(event.evidence.source_id == "incident.txt" for event in result.events)
    documents = await engine.aggregate(parser, result.events)
    assert {document.event_type for document in documents} == {
        "code",
        "fence",
        "log",
        "other",
    }
    assert sum(document.count for document in documents) == 1254
    assert sum(count for *_, count in _summary(documents, source)) == 1254


async def test_default_mixed_content_preserves_unmatched_text_and_aggregates_events():
    parser = MixedContentParser()
    engine = ParseEngine()
    result = await engine.parse(
        parser, "INFO started\nreturn value\nnotes\nanother note"
    )
    assert [(event.event_type, event.attributes) for event in result.events] == [
        ("log", {"level": "INFO", "message": "started", "text": "INFO started"}),
        ("code", {"language": "python", "text": "return value"}),
        ("other", {"text": "notes"}),
        ("other", {"text": "another note"}),
    ]
    source = "INFO started\nreturn value\nnotes\nanother note"
    documents = await engine.aggregate(parser, result.events)
    assert _summary(documents, source) == [
        ("log", "1", 1),
        ("code", "2", 1),
        ("other", "3", 1),
        ("other", "4", 1),
    ]
    (log_group,) = documents[0].groups
    assert documents[0].parser_name == "mixed-content"
    assert (log_group.pattern, log_group.severity) == ("log-level", "INFO")
    assert log_group.evidence[0].message == "started"
    assert result.events[0].evidence.line_number == 1


async def test_mixed_sections_preserve_recurrence_and_references() -> None:
    source = "INFO ready\nINFO ready\n```python\nreturn 42\n```\nINFO ready\nnote"
    parser = MixedContentParser()
    result = await parser.parse(source, ParseContext(source_id="sample.txt"))
    documents = await parser.aggregate(result.events)
    document = documents[0]
    assert _summary(documents, source) == [
        ("log", "1,2", 2),
        ("log", "6", 1),
        ("fence", "3", 1),
        ("fence", "5", 1),
        ("code", "4", 1),
        ("other", "7", 1),
    ]
    restored = await ParseEngine().materialize(
        parser, source, documents, ParseContext(source_id="sample.txt")
    )
    assert restored == result.events
    assert restored[0].attributes["text"] == "INFO ready"
    assert result.events[5].evidence.line_number == 6
    with pytest.raises(CapabilityError, match="source documents"):
        await parser.merge_aggregates([document, document])


async def test_mixed_timestamped_logs_share_kind_references_and_round_trip() -> None:
    source = (
        "2026-10-10T10:10:10+00:00 ERROR timeout\n"
        "2026-10-10T10:10:11+00:00 ERROR timeout\n"
        "2026-10-10T10:10:12+00:00 ERROR disk full\n"
        "2026-10-10T10:10:13+00:00 ERROR timeout"
    )
    parser = MixedContentParser()
    context = ParseContext(source_id="mixed-logs.txt")
    result = await parser.parse(source, context)
    (document,) = await parser.aggregate(result.events)
    assert _summary((document,), source) == [
        ("log", "1,2", 2),
        ("log", "3", 1),
        ("log", "4", 1),
    ]
    assert [entry.message for entry in document.groups[0].evidence] == [
        "timeout",
        "disk full",
        "timeout",
    ]
    assert document.first_seen is None
    assert document.last_seen is None
    restored = await ParseEngine().materialize(parser, source, (document,), context)
    assert restored == result.events
    assert [event.attributes["text"] for event in restored] == source.splitlines()
    assert [event.evidence.line_number for event in restored[:2]] == [1, 2]


def test_mixed_routes_reject_ambiguous_parser_names() -> None:
    with pytest.raises(ValueError, match="same name"):
        MixedContentParser(
            routes=[
                (RegexPattern("one", r"^A"), JSONParser()),
                (RegexPattern("two", r"^B"), JSONParser()),
            ]
        )


async def test_mixed_file_classifies_logs_code_and_other_with_byte_evidence() -> None:
    source = (
        "2026-09-30 12:00 ERROR failed\r\n"
        "```python\n"
        "print('ERROR is code')\n"
        "```\n"
        "ÃƒÂ©tiquette inconnue\n"
        "def run():\n"
        "  return 42\n"
    )
    result = await MixedContentParser().parse(
        source,
        ParseContext(source_id="mixed.txt", source_offset=15, partition_id="p0"),
    )
    assert [event.event_type for event in result.events] == [
        "log",
        "fence",
        "code",
        "fence",
        "other",
        "code",
        "code",
    ]
    assert result.events[4].attributes == {"text": "ÃƒÂ©tiquette inconnue"}
    assert [event.evidence.line_number for event in result.events] == list(range(1, 8))
    assert result.events[0].evidence.start_offset == 15
    assert result.events[1].evidence.start_offset == 15 + len(
        b"2026-09-30 12:00 ERROR failed\r\n"
    )
    assert result.events[5].evidence.start_offset == 15 + len(
        source[: source.index("def run()")].encode("utf-8")
    )
    assert result.events[-1].evidence.end_offset == 15 + len(source.encode("utf-8"))
    assert all(event.evidence.source_id == "mixed.txt" for event in result.events)
    assert all(event.evidence.partition_id == "p0" for event in result.events)
    assert loads_result(dumps_result(result)) == result
    assert result.events[2].attributes == {
        "language": "python",
        "text": "print('ERROR is code')",
    }
    assert result.events[5].attributes == {"language": "python", "text": "def run():"}
    assert {stat.pattern_name: stat.matches for stat in result.pattern_statistics} == {
        "code": 2,
        "code_fence": 3,
        "log-level": 1,
    }
    assert not MixedContentParser().capabilities.partitionable
    assert MixedContentParser().capabilities.parallel_safe
    with pytest.raises(CapabilityError):
        list(
            LinePartitioner(max_lines=2).partition(
                source.splitlines(), capabilities=MixedContentParser().capabilities
            )
        )


async def test_custom_patterns_override_defaults_and_fallback_remains_available() -> (
    None
):
    parser = MixedContentParser(
        [
            RegexPattern(
                "metric", r"^METRIC (?P<name>\w+): (?P<value>\d+)$", event_type="metric"
            ),
            PredicatePattern(
                "custom",
                lambda line: isinstance(line, str) and line.startswith("CUSTOM:"),
                lambda line: {"kind": "custom-note"},
                event_type="custom",
            ),
        ],
    )
    result = await parser.parse(b"METRIC load: 42\nCUSTOM: hello\nERROR unknown\n")
    assert [event.event_type for event in result.events] == [
        "metric",
        "custom",
        "other",
    ]
    assert result.events[0].attributes == {"name": "load", "value": "42"}
    assert result.events[1].attributes == {"kind": "custom-note"}
    assert result.events[-1].attributes == {"text": "ERROR unknown"}
    assert [event.evidence.pattern_name for event in result.events] == [
        "metric",
        "custom",
        "other",
    ]
    assert not parser.capabilities.parallel_safe


async def test_mixed_content_validation_and_fence_closing() -> None:
    with pytest.raises(ValueError, match="unique and reserved"):
        MixedContentParser([RegexPattern("other", "x")])
    with pytest.raises(TypeError, match="str or bytes"):
        await MixedContentParser().parse(object())
    with pytest.raises(UnicodeDecodeError):
        await MixedContentParser().parse(b"\xff")
    result = await MixedContentParser().parse("~~~~js\nERROR in code\n~~~~\nERROR real")
    assert [event.event_type for event in result.events] == [
        "fence",
        "code",
        "fence",
        "log",
    ]
    assert [
        event.event_type
        for event in (await MixedContentParser().parse("note\n\ncode?")).events
    ] == ["other", "other", "other"]
    assert (await MixedContentParser().parse("")).events == ()


async def test_routes_reuse_child_parsers_and_keep_their_results_and_provenance() -> (
    None
):
    source = 'ERROR database timeout\r\n{"status":"ok"}\nMETRIC load: 42\nunknown'
    parser = MixedContentParser(
        routes=[
            (RegexPattern("log-route", r"^ERROR"), ApplicationLogParser()),
            (RegexPattern("json-route", r"^\{"), JSONParser()),
            (
                RegexPattern("metric-route", r"^METRIC"),
                CLIOutputParser(
                    [RegexPattern("metric", r"^METRIC (?P<name>\w+): (?P<value>\d+)")],
                    name="metrics",
                ),
            ),
        ]
    )
    context = ParseContext(
        source_id="mixed.txt",
        correlation_id="trace",
        partition_id="part",
        source_offset=10,
    )
    result = await parser.parse(source, context)
    assert [event.event_type for event in result.events] == [
        "timeout",
        "error",
        "json_record",
        "metric",
        "other",
    ]
    assert [event.evidence.parser_name for event in result.events] == [
        "application-log",
        "application-log",
        "json",
        "metrics",
        "mixed-content",
    ]
    assert result.events[0].evidence.pattern_name == "timeout"
    assert result.events[2].attributes == {"value": {"status": "ok"}}
    assert result.events[3].attributes == {"name": "load", "value": "42"}
    assert result.events[4].attributes == {"text": "unknown"}
    assert [event.evidence.line_number for event in result.events] == [1, 1, 2, 3, 4]
    assert result.events[2].evidence.start_offset == 10 + len(
        b"ERROR database timeout\r\n"
    )
    assert result.events[3].evidence.start_offset == 10 + len(
        b'ERROR database timeout\r\n{"status":"ok"}\n'
    )
    assert all(event.evidence.partition_id == "part" for event in result.events)
    assert all(event.evidence.correlation_id == "trace" for event in result.events)
    assert loads_result(dumps_result(result)) == result
    stats = {stat.pattern_name: stat.matches for stat in result.pattern_statistics}
    assert stats["log-route:timeout"] == 1
    assert stats["metric-route:metric"] == 1
    assert stats["log-route"] == stats["json-route"] == stats["metric-route"] == 1
    assert parser.capabilities.deterministic
    assert parser.capabilities.parallel_safe
    assert not parser.capabilities.partitionable


async def test_route_failures_are_not_misclassified_as_other() -> None:
    parser = MixedContentParser(
        routes=[
            (RegexPattern("json-route", r"^\{"), JSONParser()),
            (RegexPattern("log-route", r"^ERROR"), ApplicationLogParser()),
        ]
    )
    failed = await parser.parse("{bad JSON}\n")
    assert [event.event_type for event in failed.events] == ["unparsed"]
    assert failed.events[0].attributes == {"text": "{bad JSON}"}
    assert failed.events[0].evidence.parser_name == "json"
    assert failed.events[0].evidence.line_number == 1
    assert failed.errors[0].error_type == "DecodeError"
    assert [
        event.event_type
        for event in (await parser.parse("```python\nERROR in code\n```\n")).events
    ] == ["fence", "code", "fence"]


async def test_multiline_json_route_keeps_one_record_between_other_lines() -> None:
    parser = MixedContentParser(
        routes=[
            (RegexPattern("json-route", r"^\s*[\[{]"), JSONParser()),
            (RegexPattern("log-route", r"^ERROR"), ApplicationLogParser()),
        ]
    )
    source = (
        "note\r\n"
        '{\n  "message": "brace } and quote \\" ok",\n'
        '  "items": [{"id": 1}, {"id": 2}]\n}\r\n'
        "ERROR failed\n"
        '[\n  {"id": 3}\n]\n'
        "tail"
    )
    result = await parser.parse(
        source, ParseContext(source_id="mixed.txt", source_offset=13)
    )
    assert not result.errors
    assert [event.event_type for event in result.events] == [
        "other",
        "json_record",
        "error",
        "json_record",
        "other",
    ]
    assert result.events[1].attributes["value"] == {
        "message": 'brace } and quote " ok',
        "items": [{"id": 1}, {"id": 2}],
    }
    assert result.events[3].attributes["value"] == [{"id": 3}]
    assert [event.evidence.line_number for event in result.events] == [1, 2, 6, 7, 10]
    assert result.events[1].evidence.start_offset == 13 + len(b"note\r\n")
    assert result.events[1].evidence.end_offset == 13 + len(
        source.split("ERROR", 1)[0].encode("utf-8")
    )
    assert result.events[3].evidence.start_offset == 13 + len(
        source.split("[\n", 1)[0].encode("utf-8")
    )
    assert result.events[3].evidence.end_offset == 13 + len(
        source.rsplit("tail", 1)[0].encode("utf-8")
    )
    assert result.events[1].evidence.pattern_name == "json-route"
    documents = await parser.aggregate(result.events)
    assert [(document.event_type, document.count) for document in documents] == [
        ("other", 2),
        ("json_record", 2),
        ("error", 1),
    ]
    restored = await ParseEngine().materialize(
        parser, source, documents, ParseContext(source_id="mixed.txt", source_offset=13)
    )
    assert restored == result.events


async def test_incomplete_multiline_json_does_not_consume_following_route() -> None:
    parser = MixedContentParser(
        routes=[
            (RegexPattern("json-route", r"^\{"), JSONParser()),
            (RegexPattern("log-route", r"^ERROR"), ApplicationLogParser()),
        ]
    )
    result = await parser.parse('{\n  "id": 1\nERROR failed\n')
    assert [event.event_type for event in result.events] == ["unparsed", "error"]
    assert result.events[0].attributes == {"text": '{\n  "id": 1\n'}
    assert result.events[1].evidence.line_number == 3
    assert result.errors[0].error_type == "DecodeError"
    default = MixedContentParser(
        routes=[(RegexPattern("json-route", r"^\{"), JSONParser())]
    )
    recovered = await default.parse('{\n  "id": 1\nINFO ready\n')
    assert [event.event_type for event in recovered.events] == ["unparsed", "log"]
    assert recovered.events[1].evidence.line_number == 3


async def test_empty_child_result_falls_through_to_other() -> None:
    parser = MixedContentParser(
        routes=[(RegexPattern("log-route", r"^NOTE"), ApplicationLogParser())]
    )
    assert [
        event.event_type for event in (await parser.parse("NOTE still unknown")).events
    ] == ["other"]
    assert [
        event.event_type for event in (await parser.parse("NOTICE unmatched")).events
    ] == ["other"]


def test_route_names_and_types_are_validated() -> None:
    with pytest.raises(ValueError, match="unique"):
        MixedContentParser(
            routes=[(RegexPattern("log-level", "x"), ApplicationLogParser())]
        )
    with pytest.raises(TypeError, match="Pattern, Parser"):
        MixedContentParser(routes=[(RegexPattern("invalid", "x"), object())])  # type: ignore[list-item]
    parser = MixedContentParser(
        routes=[(PredicatePattern("predicate", lambda line: True), JSONParser())]
    )
    assert not parser.capabilities.deterministic
    assert not parser.capabilities.parallel_safe


async def test_fence_routes_parse_fenced_bodies_by_declared_language() -> None:
    json_parser = JSONParser()
    parser = MixedContentParser(
        routes=[(RegexPattern("log-route", r"^ERROR"), ApplicationLogParser())],
        fence_routes={"json": json_parser},
    )
    source = (
        '```json\n{\n  "a": 1\n}\n```\n'
        "```json\n{bad\n```\n"
        "```python\nERROR in code\n```\n"
        '```\n{"b": 2}\n```\n'
    )
    result = await parser.parse(source)
    assert not result.errors
    assert [
        (event.evidence.line_number, event.event_type, event.evidence.pattern_name)
        for event in result.events
    ] == [
        (1, "fence", "code_fence"),
        (2, "json_record", "code_fence:json"),
        (5, "fence", "code_fence"),
        *(
            (line, "code" if line in {7, 10, 13} else "fence", "code_fence")
            for line in range(6, 15)
        ),
    ]
    assert result.events[1].attributes == {"value": {"a": 1}}
    assert result.events[1].evidence.parser_name == "json"
    assert result.events[1].evidence.start_offset == len("```json\n")
    statistics = {s.pattern_name: s.matches for s in result.pattern_statistics}
    assert statistics["code_fence:json"] == 1
    assert statistics["code_fence"] == 11
    engine = ParseEngine()
    documents = await engine.aggregate(parser, result.events)
    assert await engine.materialize(parser, source, documents) == result.events


def test_fence_routes_validation() -> None:
    with pytest.raises(ValueError, match="lowercase language tags"):
        MixedContentParser(fence_routes={"JSON": JSONParser()})
    with pytest.raises(ValueError, match="lowercase language tags"):
        MixedContentParser(fence_routes={"": JSONParser()})
    with pytest.raises(TypeError, match="Parser instances"):
        MixedContentParser(fence_routes={"json": object()})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="same name must be identical"):
        MixedContentParser(
            routes=[(RegexPattern("json-route", r"^\{"), JSONParser())],
            fence_routes={"json": JSONParser()},
        )
    shared = JSONParser()
    parser = MixedContentParser(
        routes=[(RegexPattern("json-route", r"^\{"), shared)],
        fence_routes={"json": shared},
    )
    assert parser.capabilities.deterministic
