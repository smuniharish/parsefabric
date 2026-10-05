import asyncio
import json
from datetime import UTC, datetime

import pytest
import structlog
from structlog.testing import CapturingLogger, capture_logs

from parsefabric.aggregation import (
    CountAggregate,
    EventAggregator,
    EvidenceAggregate,
    EvidenceAggregator,
)
from parsefabric.builtins import ApplicationLogParser
from parsefabric.capabilities import ParserCapabilities
from parsefabric.engine import ParseEngine
from parsefabric.errors import CapabilityError, DuplicateParserError
from parsefabric.models import ParseContext, ParsedEvent, ParseResult
from parsefabric.observability import (
    LifecycleEvent,
    LoggingObservabilitySink,
    ObservabilitySink,
    OpenTelemetryObservabilitySink,
)
from parsefabric.parser import AsyncParser, SemanticParser
from parsefabric.registry import ParserRegistry
from tests.support.parsers import StatefulSequenceParser


class RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.events: list[LifecycleEvent] = []

    def emit(self, event: LifecycleEvent) -> None:
        self.events.append(event)


async def test_cancelling_a_waiting_stream_reports_the_cancelled_stream() -> None:
    entered = asyncio.Event()

    class BlockingParser(AsyncParser):
        async def parse(self, source, context=None) -> ParseResult:
            entered.set()
            await asyncio.Event().wait()
            return ParseResult()

    sink = RecordingSink()
    stream = ParseEngine(sink).parse_async_iter(
        BlockingParser(name="blocked"), ["first", "second"]
    )

    # The stream is suspended inside its own wait, so the cancellation of the
    # consumer is delivered to the stream rather than to a finished generator.
    async def next_result() -> ParseResult:
        return await anext(stream)

    task = asyncio.create_task(next_result())
    async with asyncio.timeout(5):
        await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [event.name for event in sink.events] == [
        "ParserSelected",
        "ParseStarted",
        "ParseCancelled",
        "ParseCancelled",
    ]
    assert {event.parser_name for event in sink.events} == {"blocked"}


class AsyncEchoParser(AsyncParser):
    def __init__(self) -> None:
        super().__init__(name="async-echo")

    @property
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(parallel_safe=True)

    async def parse(self, source, context=None) -> ParseResult:
        return ParseResult(events=(ParsedEvent("echo", {"value": source}),))


class SlowAsyncParser(AsyncParser):
    def __init__(self) -> None:
        super().__init__(name="slow-async")
        self.active = 0
        self.peak_active = 0

    @property
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(parallel_safe=True)

    async def parse(self, source, context=None) -> ParseResult:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        await asyncio.sleep(0.005)
        self.active -= 1
        return ParseResult(events=(ParsedEvent("slow", {"value": source}),))


async def test_engine_enriches_result_and_emits_lifecycle() -> None:
    sink = RecordingSink()
    parser = ApplicationLogParser()
    result = await ParseEngine(sink).parse(
        parser, "ERROR: unavailable", ParseContext(source_id="app", partition_id="p0")
    )
    assert result.events[0].evidence.partition_id == "p0"
    names = [event.name for event in sink.events]
    assert names[:2] == ["ParserSelected", "ParseStarted"]
    assert names.count("PatternMatched") == 2
    assert names[-2:] == ["PartitionCompleted", "ParseCompleted"]


@pytest.mark.parametrize(
    "context",
    [None, ParseContext(source_id="app", partition_id="p0", correlation_id="c0")],
)
async def test_engine_reuses_events_when_evidence_is_already_complete(
    context: ParseContext | None,
) -> None:
    parser = ApplicationLogParser()
    original = await parser.parse("ERROR timeout", context)
    enriched = ParseEngine._enrich(parser, original, context)
    assert enriched == original
    assert all(
        after is before
        for before, after in zip(original.events, enriched.events, strict=True)
    )


def test_lifecycle_event_rejects_invalid_runtime_values() -> None:
    with pytest.raises(ValueError, match="timestamps"):
        LifecycleEvent("ParseStarted", occurred_at=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="attributes"):
        LifecycleEvent("ParseStarted", attributes={"invalid": []})  # type: ignore[dict-item]


async def test_logging_sink_emits_structured_lifecycle_fields_without_input() -> None:
    timestamp = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    event = LifecycleEvent(
        "ParseStarted",
        occurred_at=timestamp,
        parser_name="application-log",
        partition_id="p0",
        attributes={"record_count": 1},
    )
    with capture_logs() as logs:
        LoggingObservabilitySink().emit(event)
        await ParseEngine(LoggingObservabilitySink()).parse(
            ApplicationLogParser(), "ERROR: private customer credential"
        )

    assert logs[0] == {
        "event": "parsefabric.lifecycle",
        "parsefabric_event": "ParseStarted",
        "parser_name": "application-log",
        "partition_id": "p0",
        "event_attributes": {"record_count": 1},
        "occurred_at": timestamp.isoformat(),
        "log_level": "info",
    }
    assert "private customer credential" not in str(logs)


def test_logging_sink_accepts_application_configured_structlog_logger() -> None:
    capture = CapturingLogger()
    logger = structlog.wrap_logger(
        capture, processors=[structlog.processors.JSONRenderer()]
    )
    LoggingObservabilitySink(logger).emit(LifecycleEvent("ParseCompleted"))

    call = capture.calls[0]
    assert call.method_name == "info"
    assert call.kwargs == {}
    payload = json.loads(call.args[0])
    assert datetime.fromisoformat(payload.pop("occurred_at")).tzinfo is not None
    assert payload == {
        "event": "parsefabric.lifecycle",
        "parsefabric_event": "ParseCompleted",
        "parser_name": None,
        "partition_id": None,
        "event_attributes": {},
    }


async def test_continue_on_error_is_explicit() -> None:
    parser = ApplicationLogParser()
    with pytest.raises(TypeError):
        await ParseEngine().parse(parser, object())
    tolerant = await ParseEngine().parse(parser, object(), continue_on_error=True)
    assert tolerant.errors[0].error_type == "TypeError"


def test_registry_duplicate_lookup_replace_and_remove() -> None:
    registry = ParserRegistry()
    first = ApplicationLogParser()
    registry.register(first)
    assert registry.get(first.name) is first
    assert registry.metadata(first.name).version == "1"
    with pytest.raises(DuplicateParserError):
        registry.register(ApplicationLogParser())
    replacement = ApplicationLogParser()
    registry.register(replacement, replace=True)
    assert registry.get(first.name) is replacement
    assert registry.names() == (first.name,)
    assert registry.unregister(first.name) is replacement


@pytest.mark.asyncio
async def test_async_parser_contract_runs_natively() -> None:
    async def source():
        yield "one"
        yield "two"

    results = [
        result
        async for result in ParseEngine().parse_async_iter(
            AsyncEchoParser(), source(), max_concurrency=2
        )
    ]
    assert {str(result.events[0].attributes["value"]) for result in results} == {
        "one",
        "two",
    }


@pytest.mark.asyncio
async def test_async_stream_rejects_unsafe_concurrency() -> None:
    async def source():
        yield "first"

    with pytest.raises(CapabilityError, match="parallel execution"):
        async for _ in ParseEngine().parse_async_iter(
            StatefulSequenceParser(), source(), max_concurrency=2
        ):
            pass


@pytest.mark.asyncio
async def test_async_stream_bounds_outstanding_work() -> None:
    parser = SlowAsyncParser()

    async def source():
        for value in range(9):
            yield value

    results = [
        result
        async for result in ParseEngine().parse_async_iter(
            parser, source(), max_concurrency=2
        )
    ]
    assert len(results) == 9
    assert parser.peak_active == 2


async def test_engine_checks_aggregation_capability_and_emits_events() -> None:
    sink = RecordingSink()
    engine = ParseEngine(sink)
    parser = ApplicationLogParser()
    events = (await parser.parse("database timeout")).events
    partial = await engine.aggregate(parser, events)
    merged = await engine.merge_aggregates(parser, partial)
    assert merged[0].count == 1
    assert [event.name for event in sink.events] == [
        "AggregationStarted",
        "AggregationCompleted",
        "AggregationStarted",
        "AggregationCompleted",
    ]
    with pytest.raises(CapabilityError, match="aggregation"):
        await engine.aggregate(StatefulSequenceParser(), ())


@pytest.mark.parametrize(
    "member",
    ["aggregator", "aggregate", "merge_aggregates", "serialize", "deserialize"],
)
def test_custom_parsers_cannot_override_package_managed_aggregation(member) -> None:
    with pytest.raises(
        TypeError, match="aggregation and serialization are managed by ParseFabric"
    ):
        type("Override", (ApplicationLogParser,), {member: lambda self: None})
    with pytest.raises(TypeError, match="_build_aggregator"):
        type("Hook", (ApplicationLogParser,), {"_build_aggregator": lambda self: None})


async def test_standalone_aggregators_group_parsed_events() -> None:
    parser = ApplicationLogParser()
    aggregator = EventAggregator(group_by=("message",))
    left = await aggregator.aggregate(
        (await parser.parse("ERROR: database timeout")).events
    )
    right = await aggregator.aggregate(
        (await parser.parse("ERROR: database timeout")).events
    )
    merged = await aggregator.merge((*left, *right))
    assert all(isinstance(item, CountAggregate) for item in merged)
    assert [(item.event_type, item.key_attributes, item.count) for item in merged] == [  # type: ignore[attr-defined]
        ("error", {"message": "database timeout"}, 2),
        ("timeout", {"message": "ERROR: database timeout"}, 2),
    ]


async def test_all_parser_types_have_awaitable_aggregation() -> None:
    class SemanticEcho(SemanticParser):
        async def parse(self, source, context=None) -> ParseResult:
            return ParseResult(events=(ParsedEvent("echo"),))

    parsers = (ApplicationLogParser(), SemanticEcho(name="semantic"), AsyncEchoParser())

    async def event_stream():
        yield ParsedEvent("echo")
        yield ParsedEvent("echo")

    for parser in parsers:
        partial = await parser.aggregate(event_stream())
        assert [(item.event_type, item.count) for item in partial] == [("echo", 2)]
        (group,) = partial[0].groups
        assert [(entry.occurrences, entry.positions) for entry in group.evidence] == [
            (2, (None, None))
        ]
        assert isinstance(partial[0], EvidenceAggregate)
        assert (partial[0].source_id, partial[0].parser_name) == (None, None)
        assert await parser.merge_aggregates(partial) == partial
        with pytest.raises(CapabilityError, match="source documents"):
            await parser.merge_aggregates((*partial, *partial))


async def test_application_log_message_omits_separator_whitespace() -> None:
    result = await ApplicationLogParser().parse(
        "ERROR: database timeout\nWARNING: connection unstable"
    )
    assert (
        next(
            event.attributes["message"]
            for event in result.events
            if event.event_type == "error"
        )
        == "database timeout"
    )
    assert (
        next(
            event.attributes["message"]
            for event in result.events
            if event.event_type == "warning"
        )
        == "connection unstable"
    )


async def test_opentelemetry_sink_attaches_event_to_active_span() -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OpenTelemetryObservabilitySink(provider.get_tracer("parsefabric-tests"))

    with provider.get_tracer("test").start_as_current_span("parse-job"):
        sink.emit(
            LifecycleEvent(
                "PatternMatched",
                parser_name="application-log",
                partition_id="part-1",
                attributes={"pattern": "timeout", "event_count": 1},
            )
        )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "parse-job"
    assert spans[0].events[0].name == "PatternMatched"
    attributes = spans[0].events[0].attributes
    assert attributes is not None
    assert attributes["parsefabric.parser.name"] == "application-log"


def test_opentelemetry_sink_creates_event_span_without_parent() -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OpenTelemetryObservabilitySink(provider.get_tracer("parsefabric-tests"))
    sink.emit(LifecycleEvent("ParseCompleted", attributes={"event_count": 3}))

    spans = exporter.get_finished_spans()
    assert spans[0].name == "parsefabric.lifecycle"
    assert spans[0].events[0].name == "ParseCompleted"


async def test_engine_lifecycle_is_grouped_in_one_parse_span() -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OpenTelemetryObservabilitySink(provider.get_tracer("parsefabric-tests"))

    await ParseEngine(sink).parse(ApplicationLogParser(), "database timeout")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "parsefabric.parse"
    assert [event.name for event in spans[0].events] == [
        "ParserSelected",
        "ParseStarted",
        "PatternMatched",
        "ParseCompleted",
    ]


async def test_async_parser_cannot_be_instantiated_without_parse() -> None:
    class IncompleteAsyncParser(AsyncParser):
        def __init__(self) -> None:
            super().__init__(name="incomplete")

    import pytest

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteAsyncParser()  # type: ignore[abstract]


async def test_parsers_get_the_package_aggregator_by_default() -> None:
    class ParseOnly(SemanticParser):
        async def parse(self, source, context=None) -> ParseResult:
            return ParseResult(events=(ParsedEvent("echo", {"message": "hi"}),))

    parser = ParseOnly(name="parse-only")
    assert isinstance(parser.aggregator, EvidenceAggregator)
    assert parser.aggregator.lossless
    assert not parser.aggregator.requires_source
    engine = ParseEngine()
    result = await engine.parse(parser, "x")
    aggregates = await engine.aggregate(parser, result.events)
    (document,) = aggregates
    assert document.groups[0].evidence[0].message == "hi"
    assert await engine.materialize(parser, "x", aggregates) == result.events

    deterministic = ApplicationLogParser()
    assert deterministic.aggregator.requires_source
