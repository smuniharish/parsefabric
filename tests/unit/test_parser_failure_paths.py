"""Public parser and result boundaries reject malformed inputs explicitly."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from parsefabric import Evidence, ParseContext, ParsedEvent, ParseResult
from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    PythonTracebackParser,
    TimestampedLogParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import (
    CapabilityError,
    ConfigurationError,
    ParseError,
    SerializationError,
)
from parsefabric.parser import AsyncParser, DeterministicParser, SemanticParser
from parsefabric.patterns import ExactPattern, RegexPattern
from parsefabric.serialization import dumps_result, iter_ndjson, loads_result
from tests.support.parsers import StatefulSequenceParser


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_type", ""),
        ("timestamp", "bad"),
        ("severity", 1),
        ("confidence", True),
        ("confidence", -0.1),
        ("confidence", float("nan")),
        ("attributes", []),
        ("attributes", {"x": object()}),
        ("attributes", {"x": float("inf")}),
        ("attributes", {1: "x"}),
        ("attributes", {"x": "\ud800"}),
        ("evidence", {}),
    ],
)
def test_invalid_event_models(field: str, value: Any) -> None:
    kwargs: dict[str, Any] = {"event_type": "x", field: value}
    with pytest.raises(ValueError):
        ParsedEvent(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_offset", True),
        ("end_offset", True),
        ("line_number", False),
        ("start_offset", -1),
        ("end_offset", -1),
        ("line_number", 0),
    ],
)
def test_invalid_evidence_positions(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        Evidence(**{field: value})


@pytest.mark.parametrize("offset", [True, -1, 1.5])
def test_invalid_source_offsets(offset: Any) -> None:
    with pytest.raises(ValueError):
        ParseContext(source_offset=offset)


def _result_with_event(change: dict[str, Any]) -> str:
    event = ParsedEvent("x").to_dict() | change
    return json.dumps(ParseResult().to_dict() | {"events": [event]})


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2"},
        {"event_type": 1},
        {"attributes": []},
        {"attributes": {"x": [[[]]] * 2, "y": None} | {"z": {"w": "\ud800"}}},
        {"evidence": []},
        {"evidence": Evidence().to_dict() | {"extra": None}},
        {"severity": 1},
        {"confidence": True},
        {"timestamp": 1},
        {"timestamp": "2026-01-01T00:00:00"},
        {"unknown": 1},
    ],
)
def test_event_wire_decoder_rejects_invalid_fields(change: dict[str, Any]) -> None:
    with pytest.raises(SerializationError):
        loads_result(_result_with_event(change))


@pytest.mark.parametrize("field", ["event_type", "attributes", "evidence"])
def test_event_wire_decoder_requires_every_field(field: str) -> None:
    event = ParsedEvent("x").to_dict()
    del event[field]
    with pytest.raises(SerializationError, match="missing"):
        loads_result(json.dumps(ParseResult().to_dict() | {"events": [event]}))


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":"1","schema_version":"1"}',
        '{"events":[NaN]}',
        b'\xff{"schema_version":"1"}',
        "[" * 100_000 + "]" * 100_000,
    ],
    ids=["duplicate-key", "nan", "invalid-utf8", "deep-nesting"],
)
def test_result_decoder_rejects_ambiguous_or_malformed_json(
    payload: str | bytes,
) -> None:
    with pytest.raises(SerializationError):
        loads_result(payload)


def test_result_decoder_rejects_non_text_payloads() -> None:
    with pytest.raises(TypeError, match="str or bytes"):
        loads_result(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ParseResult"):
        dumps_result({})  # type: ignore[arg-type]


def test_result_wire_requires_objects_and_ndjson_is_one_result_per_line() -> None:
    for value in [[], {"schema_version": "1", "events": [None]}]:
        with pytest.raises(SerializationError):
            loads_result(json.dumps(value))
    result = ParseResult()
    assert list(iter_ndjson([result, result])) == [dumps_result(result) + "\n"] * 2


@pytest.mark.parametrize(
    "parser",
    [
        ApplicationLogParser(),
        PythonTracebackParser(),
        TimestampedLogParser(),
        StatefulSequenceParser(),
    ],
)
async def test_text_parsers_reject_nontext(parser: Any) -> None:
    with pytest.raises(TypeError):
        await parser.parse(1)


async def test_traceback_and_json_failure_paths() -> None:
    assert (await PythonTracebackParser().parse(b"ValueError: bad")).events
    with pytest.raises(ParseError):
        await PythonTracebackParser().parse("Traceback (most recent call last):\n")
    with pytest.raises(ParseError, match="Unicode"):
        await JSONParser().parse("\ud800")
    with pytest.raises(UnicodeDecodeError):
        await JSONParser().parse(b"\xff")


@pytest.mark.parametrize(
    "source",
    [
        "not a log",
        "2026-01-01T00:00:00 INFO message",
    ],
)
async def test_timestamped_input_errors(source: str) -> None:
    with pytest.raises(ParseError):
        await TimestampedLogParser().parse(source)


async def test_timestamped_custom_pattern_incomplete_and_invalid_timestamp() -> None:
    parser = TimestampedLogParser(
        line_pattern=r"(?P<at>\S+) (?P<level>\S*) (?P<message>.*)"
    )
    with pytest.raises(ParseError, match="incomplete"):
        await parser.parse("2026-01-01T00:00:00Z INFO ")
    with pytest.raises(ParseError, match="timestamp"):
        await parser.parse("invalid INFO ready")
    assert (await parser.parse(b"2026-01-01T00:00:00Z INFO ready")).events


async def test_command_parser_rejects_patterns_nontext_and_invalid_library_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = CLIOutputParser(command="df")
    with pytest.raises(ConfigurationError):
        parser.register_pattern(ExactPattern("x", "x"))
    with pytest.raises(TypeError):
        await parser.parse(1)
    monkeypatch.setattr("jc.parse", lambda *args, **kwargs: ["not a record"])
    result = await parser.parse("bad")
    assert len(result.errors) == 1
    assert result.errors[0].error_type == "ParseError"
    assert result.events[0].event_type == "unparsed"


def test_deterministic_patterns_reject_duplicates_and_missing_removal() -> None:
    pattern = RegexPattern("x", "x")
    with pytest.raises(ValueError):
        DeterministicParser([pattern, pattern], name="x")
    parser = DeterministicParser([pattern], name="x")
    with pytest.raises(ConfigurationError):
        parser.unregister_pattern("missing")
    assert parser.unregister_pattern("x") is pattern
    assert not parser.patterns
    assert ExactPattern("x", "expected").match("different") is None
    assert RegexPattern("x", "x").match(object()) is None


def test_async_and_semantic_names_must_be_nonempty() -> None:
    class Async(AsyncParser):
        async def parse(
            self, source: object, context: ParseContext | None = None
        ) -> ParseResult:
            return ParseResult()

    with pytest.raises(ValueError):
        Async(name="")

    class Semantic(SemanticParser):
        async def parse(
            self, source: object, context: ParseContext | None = None
        ) -> ParseResult:
            return ParseResult()

    with pytest.raises(ValueError):
        Semantic(name="")


async def test_engine_async_iter_many_continue_on_error_and_merge_errors() -> None:
    engine, parser = ParseEngine(), ApplicationLogParser()

    async def sources() -> AsyncIterator[object]:
        yield "timeout"
        yield 1

    streamed = [
        result
        async for result in engine.parse_iter(parser, sources(), continue_on_error=True)
    ]
    assert len(streamed) == 2
    assert streamed[1].errors[0].error_type == "TypeError"
    assert await engine.parse_many(parser, sources(), continue_on_error=True) == tuple(
        streamed
    )
    assert await engine.parse_many(parser, ["timeout"]) == (streamed[0],)
    aggregates = await engine.aggregate(parser, streamed[0].events)
    assert await engine.merge_aggregates(parser, aggregates) == aggregates
    with pytest.raises(CapabilityError, match="checksummed"):
        await engine.merge_aggregates(parser, [*aggregates, *aggregates])


async def test_direct_parse_cancellation_is_not_converted_into_issue() -> None:
    entered = asyncio.Event()

    class Blocking(AsyncParser):
        async def parse(
            self, source: object, context: ParseContext | None = None
        ) -> ParseResult:
            entered.set()
            await asyncio.Event().wait()
            return ParseResult()

    parser = Blocking(name="blocked")
    task = asyncio.create_task(ParseEngine().parse(parser, "", continue_on_error=True))
    try:
        async with asyncio.timeout(5):
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
