"""Targeted tests for validation and control-flow branches of every module."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from parsefabric import (
    Evidence,
    EvidenceAggregator,
    ParseContext,
    ParsedEvent,
    ParserCapabilities,
)
from parsefabric._summary_review import Fact, check_claims
from parsefabric.aggregation import CountAggregate, EvidenceEntry, EvidenceGroup, codec
from parsefabric.builtins import (
    CLIOutputParser,
    CodeDetector,
    JSONParser,
    MixedContentParser,
    PythonTracebackParser,
)
from parsefabric.errors import (
    ParseError,
    RegistryError,
    SerializationError,
    SummaryValidationError,
)
from parsefabric.observability import LifecycleEvent, OpenTelemetryObservabilitySink
from parsefabric.parser import DeterministicParser
from parsefabric.partitioning import LinePartitioner
from parsefabric.patterns import RegexPattern
from parsefabric.registry import ParserRegistry
from parsefabric.summarization import DEFAULT_MAX_AGGREGATES, EvidenceSummarizer

_FACTS = (Fact("e0", "s", "error", "ERROR", "boom", 1, (1,), (), False),)


def test_claim_checks_report_unknown_context_and_blank_text() -> None:
    claim = {"text": "Boom.", "evidence_ids": ["e0"], "occurrences": 1}
    _, issues = check_claims(
        json.dumps({"claims": [claim | {"context_ids": ["missing"]}]}), _FACTS
    )
    assert issues == ["Claim 1: unknown context IDs.", _MISSING_REQUIRED]
    _, issues = check_claims(json.dumps({"claims": [claim | {"text": "   "}]}), _FACTS)
    assert issues == ["Claim 1: text must not be blank."]
    claims, issues = check_claims("not json", _FACTS)
    assert claims.claims == []
    assert issues == ["Return valid JSON matching the supplied Claims schema."]


_MISSING_REQUIRED = "Include every error/warning finding with its exact total."


async def _fence_aggregates() -> Any:
    parser = MixedContentParser(code_languages=())
    result = await parser.parse("```\n```", ParseContext(source_id="fences"))
    return await EvidenceAggregator().aggregate(result.events)


async def test_summary_without_task_relevant_claims_fails_explicitly() -> None:
    model = FakeListChatModel(responses=['{"claims": []}', '{"issues": []}'])
    summarizer = EvidenceSummarizer(model)
    assert summarizer.max_aggregates == DEFAULT_MAX_AGGREGATES
    with pytest.raises(SummaryValidationError, match="no task-relevant claims"):
        await summarizer.summarize(await _fence_aggregates())


async def test_summarizer_rejects_invalid_drafts_and_items() -> None:
    summarizer = EvidenceSummarizer(FakeListChatModel(responses=["unused"]))
    aggregates = await _fence_aggregates()
    for draft in ("", "   "):
        with pytest.raises(ValueError, match="draft"):
            await summarizer.summarize(aggregates, draft=draft)
    with pytest.raises(TypeError, match="EvidenceAggregate"):
        await summarizer.summarize([object()])  # type: ignore[list-item]


def test_count_aggregates_require_object_keys() -> None:
    with pytest.raises(ValueError, match="key attributes must be a JSON object"):
        CountAggregate("x", 1, None, None, [])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"format": codec.FORMAT, "aggregates": {}}, "aggregates must be a list"),
        ({"format": "other/1", "aggregates": []}, "expected a"),
        ({"format": codec.FORMAT}, "missing aggregates"),
    ],
)
def test_aggregate_documents_are_validated(
    document: dict[str, Any], message: str
) -> None:
    with pytest.raises(SerializationError, match=message):
        codec.decode(json.dumps(document))


async def _retained_document() -> dict[str, Any]:
    events = [ParsedEvent("x", {"message": "m"}, evidence=Evidence(line_number=1))]
    (aggregate,) = await EvidenceAggregator().aggregate(events)
    return aggregate.to_dict()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda entry: entry.update(positions={}), "positions must be a list"),
        (lambda entry: entry.pop("sequence"), "must appear together"),
        (
            lambda entry: entry.update(events=[], sequence=[]),
            "retained events must not be empty",
        ),
        (lambda entry: entry.update(extra=1), "unknown fields extra"),
    ],
)
async def test_evidence_entries_are_decoded_strictly(change: Any, message: str) -> None:
    document = await _retained_document()
    change(document["groups"][0]["evidence"][0])
    payload = json.dumps({"format": codec.FORMAT, "aggregates": [document]})
    with pytest.raises(SerializationError, match=message):
        codec.decode(payload)


def test_evidence_group_totals_its_occurrences() -> None:
    group = EvidenceGroup(
        "p", None, (EvidenceEntry("a", 2, (1, 2)), EvidenceEntry("b", 1, (None,)))
    )
    assert group.occurrences == 3


async def test_runs_break_between_unlocated_spans_that_do_not_touch() -> None:
    events = [
        ParsedEvent(
            "x", {"message": "m"}, evidence=Evidence(start_offset=0, end_offset=2)
        ),
        ParsedEvent(
            "x", {"message": "m"}, evidence=Evidence(start_offset=2, end_offset=4)
        ),
        ParsedEvent(
            "x", {"message": "m"}, evidence=Evidence(start_offset=9, end_offset=9)
        ),
    ]
    (aggregate,) = await EvidenceAggregator().aggregate(events)
    assert [entry.occurrences for entry in aggregate.groups[0].evidence] == [2, 1]


async def test_cli_command_mode_accepts_bytes_and_rejects_non_json_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = CLIOutputParser(command="kv")
    assert parser.command == "kv"
    assert CLIOutputParser([]).command is None
    (record,) = (await parser.parse(b"name=shop")).events
    assert record.attributes == {"name": "shop"}

    from parsefabric.builtins import cli_output

    monkeypatch.setattr(
        cli_output.jc, "parse", lambda *args, **kwargs: [{"value": float("nan")}]
    )
    result = await parser.parse("name=shop")
    assert [event.event_type for event in result.events] == ["unparsed"]
    assert result.errors[0].error_type == "ParseError"
    assert "non-finite" in result.errors[0].message


def test_code_detection_distinguishes_statements_calls_and_prose() -> None:
    sql = CodeDetector(["sql"])
    assert sql.detect("SET x = 1;") is None
    assert sql.detect("SELECT 1;") == "sql"
    assert sql.detect("select the order") is None
    python = CodeDetector(["python"])
    assert python.detect("print('hello')") == "python"
    assert python.detect("Total (approx)") is None
    disabled = CodeDetector([])
    assert disabled.languages == ()
    assert disabled.detect("print('hello')") is None


async def test_json_routes_close_values_on_mismatched_brackets() -> None:
    parser = MixedContentParser(
        routes=[(RegexPattern("json-line", r"^[\[{]"), JSONParser())],
        code_languages=(),
    )
    result = await parser.parse('{"a": ]\nnext line')
    assert [event.event_type for event in result.events] == ["unparsed", "other"]
    assert result.errors[0].error_type == "DecodeError"


@pytest.mark.parametrize("kind", ["routes", "fence_routes"])
def test_mixed_content_cannot_route_to_itself(kind: str) -> None:
    class SelfRouting(MixedContentParser):
        def __init__(self) -> None:
            if kind == "routes":
                super().__init__(routes=[(RegexPattern("self", "x"), self)])
            else:
                super().__init__(fence_routes={"self": self})

    with pytest.raises(TypeError, match="itself"):
        SelfRouting()


async def test_traceback_ignores_source_lines_between_frames() -> None:
    source = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 3, in main\n'
        "    raise KeyError(name)\n"
        "KeyError: 'shop'\n"
    )
    (event,) = (await PythonTracebackParser().parse(source)).events
    assert event.attributes["exception_type"] == "KeyError"
    assert event.attributes["message"] == "'shop'"
    with pytest.raises(ParseError, match="no Python exception"):
        await PythonTracebackParser().parse("    raise KeyError(name)")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"stateful": True, "parallel_safe": True}, "stateful parsers"),
        ({"requires_order": True, "parallel_safe": True}, "order-dependent parsers"),
    ],
)
def test_capabilities_reject_unsafe_concurrency(
    arguments: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ParserCapabilities(**arguments)


def test_event_evidence_replacement_validates_and_keeps_subclasses() -> None:
    @dataclass(frozen=True, slots=True)
    class TaggedEvent(ParsedEvent):
        tag: str = "t"

    event = TaggedEvent("x", {"a": 1}, tag="kept")
    moved = event.with_evidence(Evidence(line_number=3))
    assert isinstance(moved, TaggedEvent)
    assert (moved.tag, moved.evidence.line_number, moved.attributes) == (
        "kept",
        3,
        {"a": 1},
    )
    with pytest.raises(ValueError, match="Evidence instance"):
        ParsedEvent("x").with_evidence({})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "arguments",
    [{"name": ""}, {"name": "x", "parser_name": 1}, {"name": "x", "partition_id": 2}],
)
def test_lifecycle_events_validate_names_and_identifiers(
    arguments: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="lifecycle event"):
        LifecycleEvent(**arguments)


def test_terminal_events_close_the_innermost_matching_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OpenTelemetryObservabilitySink(provider.get_tracer("test"))
    sink.emit(LifecycleEvent("ExecutionSubmitted"))
    sink.emit(LifecycleEvent("ParseCompleted"))
    assert exporter.get_finished_spans() == ()
    sink.emit(LifecycleEvent("ParserSelected"))
    sink.emit(LifecycleEvent("ExecutionSubmitted"))
    sink.emit(LifecycleEvent("ParseCompleted"))
    (parse,) = exporter.get_finished_spans()
    assert parse.name == "parsefabric.parse"
    sink.emit(LifecycleEvent("ExecutionCompleted"))
    sink.emit(LifecycleEvent("ExecutionCompleted"))
    names = [span.name for span in exporter.get_finished_spans()]
    assert names == [
        "parsefabric.parse",
        "parsefabric.execution",
        "parsefabric.execution",
    ]


async def test_deterministic_parsers_pickle_and_stop_at_first_match() -> None:
    parser = DeterministicParser(
        [
            RegexPattern("high", r"x", priority=2),
            RegexPattern("low", r"x", priority=1),
        ],
        name="first",
        first_match_only=True,
    )
    restored = pickle.loads(pickle.dumps(parser))
    result = await restored.parse("x\ny\nx")
    assert [event.evidence.pattern_name for event in result.events] == ["high", "high"]
    restored.register_pattern(RegexPattern("other", "y"))
    assert [pattern.name for pattern in restored.patterns] == ["high", "low", "other"]


def test_partitioner_rejects_non_text_records() -> None:
    partitions = LinePartitioner().partition(
        ["ok", b"bytes"],  # type: ignore[list-item]
        capabilities=DeterministicParser([], name="x").capabilities,
    )
    with pytest.raises(TypeError, match="requires strings"):
        list(partitions)


def test_registry_lookup_of_missing_parser_fails_explicitly() -> None:
    registry = ParserRegistry()
    with pytest.raises(RegistryError, match="not registered"):
        registry.get("missing")
    with pytest.raises(RegistryError, match="not registered"):
        registry.metadata("missing")
