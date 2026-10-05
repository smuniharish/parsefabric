"""Regression tests for defects found in the module audit and new validations."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from parsefabric import ParseContext, ParsedEvent, ParserCapabilities, ParseResult
from parsefabric.aggregation import EvidenceAggregator
from parsefabric.builtins import (
    ApplicationLogParser,
    JSONParser,
    MixedContentParser,
    PythonTracebackParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import (
    CapabilityError,
    DuplicateParserError,
    ParseIssue,
    RegistryError,
)
from parsefabric.execution import (
    AsyncExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.models import Evidence, PatternStatistic
from parsefabric.observability import LifecycleEvent, _nanoseconds
from parsefabric.parser import DeterministicParser
from parsefabric.partitioning import LinePartitioner
from parsefabric.patterns import (
    ExactPattern,
    PredicatePattern,
    RegexPattern,
    StructuredPattern,
)
from parsefabric.registry import ParserRegistry


class Doubler:
    """Picklable callable object with an asynchronous ``__call__``."""

    async def __call__(self, value: int) -> int:
        await asyncio.sleep(0)
        return value * 2


def _record_parser() -> DeterministicParser:
    return DeterministicParser(
        [RegexPattern("record", r"^ERROR (?P<message>.*)$")], name="records"
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r", "\u2028"])
async def test_blank_lines_break_runs_for_every_line_ending(newline: str) -> None:
    parser = _record_parser()
    source = newline.join(["ERROR x", "ERROR x", "", "ERROR x"])
    (aggregate,) = await parser.aggregate((await parser.parse(source)).events)
    assert [entry.positions for entry in aggregate.groups[0].evidence] == [
        (1, 2),
        (4,),
    ]


async def test_runs_use_line_numbers_when_spans_exclude_terminators() -> None:
    def event(line: int, start: int) -> ParsedEvent:
        return ParsedEvent(
            "x",
            {"message": "m"},
            evidence=Evidence(
                start_offset=start, end_offset=start + 1, line_number=line
            ),
        )

    (aggregate,) = await EvidenceAggregator().aggregate(
        [event(1, 0), event(2, 3), event(4, 8), event(4, 8)]
    )
    assert [entry.positions for entry in aggregate.groups[0].evidence] == [
        (1, 2),
        (4, 4),
    ]


@pytest.mark.parametrize(
    "parser",
    [ApplicationLogParser(), MixedContentParser(code_languages=())],
    ids=["application-log", "mixed-content"],
)
async def test_builtin_patterns_stay_linear_on_whitespace_heavy_lines(
    parser: Any,
) -> None:
    line = "ERROR database timeout" + " \t" * 100_000 + "x" + " " * 100_000
    started = time.perf_counter()
    result = await parser.parse(line)
    assert time.perf_counter() - started < 2
    messages = {event.attributes.get("message") for event in result.events}
    assert line.rstrip() in messages or line.rstrip()[len("ERROR ") :] in messages


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("  ERROR: retrying   ", "retrying"),
        ("ERROR", ""),
        ("2026-01-01T00:00:00Z WARN slow\u00a0disk\u3000", "slow\u00a0disk"),
    ],
)
async def test_mixed_log_level_message_drops_only_trailing_whitespace(
    line: str, message: str
) -> None:
    (event,) = (await MixedContentParser(code_languages=()).parse(line)).events
    assert event.attributes["message"] == message
    assert event.attributes["text"] == line


async def test_materialize_accepts_aggregates_in_any_order() -> None:
    parser = ApplicationLogParser()
    engine = ParseEngine()
    source = "ERROR database timeout\nWARN slow disk\nretry attempt 2"
    result = await engine.parse(parser, source)
    aggregates = await engine.aggregate(parser, result.events)
    assert len(aggregates) > 2
    restored = await engine.materialize(parser, source, tuple(reversed(aggregates)))
    assert restored == result.events


def test_partitioner_limits_are_read_only_and_validated() -> None:
    partitioner = LinePartitioner(max_lines=2, max_bytes=10)
    assert (partitioner.max_lines, partitioner.max_bytes) == (2, 10)
    with pytest.raises(AttributeError):
        partitioner.max_lines = 0  # type: ignore[misc]
    for value in (0, True, 1.5):
        with pytest.raises(ValueError, match="max_lines"):
            LinePartitioner(max_lines=value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "backend_type", [AsyncExecutionBackend, ThreadExecutionBackend]
)
async def test_backends_await_results_of_async_callable_objects(
    backend_type: Any,
) -> None:
    async with backend_type() as backend:
        assert await backend.run(Doubler(), 21) == 42


async def test_process_backend_awaits_async_callable_objects() -> None:
    async with ProcessExecutionBackend(max_workers=1) as backend:
        assert await backend.run(Doubler(), 4) == 8


@pytest.mark.parametrize("workers", [0, -1, True, 1.5])
def test_pool_backends_validate_worker_counts(workers: Any) -> None:
    with pytest.raises(ValueError, match="max_workers"):
        ThreadExecutionBackend(max_workers=workers)
    with pytest.raises(ValueError, match="max_workers"):
        ProcessExecutionBackend(max_workers=workers)


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 10, 4, 12, 0, 0, 123457, tzinfo=UTC),
        datetime(1999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone(timedelta(hours=5))),
        datetime(1970, 1, 1, tzinfo=UTC),
    ],
)
def test_opentelemetry_timestamps_are_exact_nanoseconds(moment: datetime) -> None:
    delta = moment - datetime(1970, 1, 1, tzinfo=UTC)
    expected = (delta // timedelta(microseconds=1)) * 1_000
    assert _nanoseconds(moment) == expected


def test_lifecycle_event_owns_its_attributes() -> None:
    attributes: dict[str, str | int | float | bool | None] = {"count": 1}
    event = LifecycleEvent("x", attributes=attributes)
    attributes["count"] = 2
    assert event.attributes == {"count": 1}
    with pytest.raises(ValueError, match="scalar"):
        LifecycleEvent("x", attributes={"value": float("nan")})


def test_empty_application_log_pattern_list_means_no_patterns() -> None:
    assert ApplicationLogParser(patterns=[]).patterns == ()
    assert len(ApplicationLogParser().patterns) == 10


def test_mixed_content_determinism_follows_pattern_types() -> None:
    regex = MixedContentParser([RegexPattern("e", r"ERROR")], code_languages=())
    assert regex.capabilities.deterministic
    assert regex.capabilities.parallel_safe
    assert regex.aggregator.requires_source
    predicate = MixedContentParser(
        [PredicatePattern("p", lambda value: True)], code_languages=()
    )
    assert not predicate.capabilities.deterministic
    assert not predicate.capabilities.parallel_safe


class _EntryPoint:
    def __init__(self, name: str, factory: Any) -> None:
        self.name = name
        self._factory = factory

    def load(self) -> Any:
        return self._factory


def _named(name: str) -> Any:
    return lambda: DeterministicParser([], name=name)


def _broken() -> Any:
    raise ImportError("broken plugin")


@pytest.mark.parametrize(
    ("entry_points", "error"),
    [
        ([("a", _named("a")), ("b", _broken)], RegistryError),
        ([("a", _named("a")), ("b", lambda: object())], RegistryError),
        ([("a", _named("a")), ("b", _named("a"))], DuplicateParserError),
        ([("a", _named("a")), ("taken", _named("taken"))], DuplicateParserError),
    ],
)
def test_registry_discovery_is_atomic(
    monkeypatch: pytest.MonkeyPatch, entry_points: list[Any], error: type[Exception]
) -> None:
    from parsefabric import registry as module

    monkeypatch.setattr(
        module,
        "entry_points",
        lambda group: [_EntryPoint(name, factory) for name, factory in entry_points],
    )
    registry = ParserRegistry()
    registry.register(DeterministicParser([], name="taken"))
    with pytest.raises(error):
        registry.discover()
    assert registry.names() == ("taken",)
    with pytest.raises(TypeError, match="Parser"):
        registry.register(object())  # type: ignore[arg-type]


def test_registry_discovery_registers_every_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from parsefabric import registry as module

    monkeypatch.setattr(
        module,
        "entry_points",
        lambda group: [_EntryPoint("a", _named("a")), _EntryPoint("b", _named("b"))],
    )
    registry = ParserRegistry()
    assert registry.discover() == ("a", "b")
    assert registry.names() == ("a", "b")


@pytest.mark.parametrize(
    "arguments",
    [
        {"deterministic": 1},
        {"aggregatable": "yes"},
        {"partition_framing": "line"},
        {
            "deterministic": True,
            "parallel_safe": True,
            "partitionable": True,
            "partition_framing": "",
        },
        {
            "deterministic": True,
            "parallel_safe": True,
            "partitionable": True,
        },
    ],
)
def test_capabilities_reject_invalid_declarations(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ParserCapabilities(**arguments)


def test_capability_requirements_explain_the_conflict() -> None:
    capabilities = ParserCapabilities(
        deterministic=True,
        parallel_safe=True,
        partitionable=True,
        partition_framing="record",
    )
    with pytest.raises(CapabilityError, match="'record' does not match 'line'"):
        capabilities.require_framing("line")


@pytest.mark.parametrize(
    "build",
    [
        lambda: RegexPattern("", "x"),
        lambda: RegexPattern(1, "x"),  # type: ignore[arg-type]
        lambda: RegexPattern("x", "x", priority=True),
        lambda: RegexPattern("x", "x", event_type=""),
        lambda: RegexPattern("x", b"x"),  # type: ignore[arg-type]
        lambda: RegexPattern("x", "x", severity=1),  # type: ignore[arg-type]
        lambda: ExactPattern("x", 1, attributes={"a": object()}),
        lambda: ExactPattern("x", 1, severity=1),  # type: ignore[arg-type]
        lambda: PredicatePattern("x", 1),  # type: ignore[arg-type]
        lambda: PredicatePattern("x", bool, severity=1),  # type: ignore[arg-type]
        lambda: StructuredPattern("x", bool, extractor=1),  # type: ignore[arg-type]
    ],
)
def test_patterns_validate_their_definition(build: Any) -> None:
    with pytest.raises(ValueError):
        build()


def test_pattern_identity_is_read_only_and_matches_are_independent() -> None:
    pattern = ExactPattern(
        "exact", "ok", priority=3, metadata={"owner": "ops"}, attributes={"a": [1]}
    )
    assert (pattern.name, pattern.priority, pattern.event_type) == ("exact", 3, "exact")
    assert pattern.expected == "ok"
    assert dict(pattern.metadata) == {"owner": "ops"}
    with pytest.raises(AttributeError):
        pattern.priority = 9  # type: ignore[misc]
    with pytest.raises(TypeError):
        pattern.metadata["owner"] = "x"  # type: ignore[index]
    first = pattern.match("ok")
    assert first is not None
    first.attributes["a"] = []
    second = pattern.match("ok")
    assert second is not None
    assert second.attributes == {"a": [1]}
    regex = RegexPattern("r", r"(?P<word>\w+)", flags=2)
    assert (regex.expression, regex.flags & 2) == (r"(?P<word>\w+)", 2)


@pytest.mark.parametrize(
    "build",
    [
        lambda: DeterministicParser([], name=""),
        lambda: DeterministicParser([], name="x", version=""),
        lambda: DeterministicParser([], name=1),  # type: ignore[arg-type]
    ],
)
def test_parser_identities_are_validated(build: Any) -> None:
    with pytest.raises(ValueError, match="name and version"):
        build()


def test_deterministic_parser_validates_its_configuration() -> None:
    with pytest.raises(TypeError, match="Pattern"):
        DeterministicParser([object()], name="x")  # type: ignore[list-item]
    with pytest.raises(TypeError, match="first_match_only"):
        DeterministicParser([], name="x", first_match_only=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="capabilities"):
        DeterministicParser([], name="x", capabilities={})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Pattern"):
        DeterministicParser([], name="x").register_pattern(object())  # type: ignore[arg-type]


async def test_traceback_event_spans_the_whole_input() -> None:
    source = (
        'Traceback (most recent call last):\n  File "a.py", line 1, in f\nKeyError: 1\n'
    )
    (event,) = (
        await PythonTracebackParser().parse(source, ParseContext(source_offset=7))
    ).events
    evidence = event.evidence
    assert (evidence.start_offset, evidence.end_offset, evidence.line_number) == (
        7,
        7 + len(source.encode()),
        1,
    )
    with pytest.raises(Exception, match="valid Unicode"):
        await PythonTracebackParser().parse("KeyError: \ud800")


def test_parse_issue_validation_and_unicode_safe_messages() -> None:
    issue = ParseIssue.from_exception(ValueError("bad \udcff byte"), input_index=0)
    assert issue.message == "bad \\udcff byte"
    assert ParseIssue.from_dict(issue.to_dict()) == issue
    invalid: list[dict[str, Any]] = [
        {"error_type": "", "message": "x"},
        {"error_type": "E", "message": 1},
        {"error_type": "E", "message": "x", "source_id": 1},
        {"error_type": "E", "message": "x", "input_index": -1},
        {"error_type": "E", "message": "x", "input_index": True},
    ]
    for arguments in invalid:
        with pytest.raises(ValueError):
            ParseIssue(**arguments)


def test_parse_results_normalize_and_validate_their_items() -> None:
    event = ParsedEvent("x")
    result = ParseResult(events=[event], warnings=["w"])  # type: ignore[arg-type]
    assert result.events == (event,)
    assert result.warnings == ("w",)
    invalid: list[dict[str, Any]] = [
        {"events": "x"},
        {"events": [object()]},
        {"warnings": [1]},
        {"errors": [object()]},
        {"pattern_statistics": [PatternStatistic("a", 1), PatternStatistic("a", 2)]},
        {"parser_name": 1},
    ]
    for arguments in invalid:
        with pytest.raises(ValueError):
            ParseResult(**arguments)


async def test_json_parser_reports_excessive_nesting_as_an_issue() -> None:
    for depth in (300, 100_000):
        text = "[" * depth + "]" * depth
        result = await JSONParser().parse(text)
        assert [event.event_type for event in result.events] == ["unparsed"]
        assert result.errors[0].error_type == "ParseError"
        assert "nests deeper" in result.errors[0].message
    with pytest.raises(Exception, match="JSON-compatible"):
        await JSONParser().parse({"value": object()})
