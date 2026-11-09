"""The public contract checks accept every built-in and reject broken subclasses."""

from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Sequence
from typing import Any, override

import pytest

from parsefabric import ParseContext, ParsedEvent, ParseResult
from parsefabric.aggregation import (
    Aggregate,
    Aggregator,
    CountAggregate,
    EventAggregator,
    EvidenceAggregator,
)
from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    MixedContentParser,
    PythonTracebackParser,
    TimestampedLogParser,
)
from parsefabric.builtins.cli_output import JcBackend
from parsefabric.builtins.code_detection import CodeDetector, TreeSitterCodeDetector
from parsefabric.capabilities import ParserCapabilities
from parsefabric.codecs import AggregateCodec, EvidenceCodec, StrictJSONCodec
from parsefabric.compression import ApproximateTokenizer, Tokenizer
from parsefabric.execution import (
    AsyncExecutionBackend,
    ExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.llm import ChatMessage, LanguageModel
from parsefabric.observability import (
    CompositeObservabilitySink,
    LoggingObservabilitySink,
    NullObservabilitySink,
    OpenTelemetryObservabilitySink,
)
from parsefabric.parser import AsyncParser, DeterministicParser, Parser
from parsefabric.partitioning import LinePartitioner, Partition, Partitioner
from parsefabric.patterns import ExactPattern, PatternMatch, PredicatePattern, RegexPattern
from parsefabric.registry import InMemoryParserRegistry, ParserRegistry
from parsefabric.testing import (
    check_aggregator,
    check_code_detector,
    check_codec,
    check_command_output_backend,
    check_execution_backend,
    check_json_codec,
    check_language_model,
    check_observability_sink,
    check_parser,
    check_parser_registry,
    check_partitioner,
    check_pattern,
    check_tokenizer,
)

LOG = (
    "2026-01-01T00:00:00Z ERROR checkout timeout after 30s\n"
    "2026-01-01T00:00:01Z INFO retry scheduled\n"
)
TIMESTAMPED = "2026-01-01T00:00:00Z ERROR disk full\n2026-01-01T00:00:01Z INFO ok\n"
TRACEBACK = (
    "Traceback (most recent call last):\n  File \"app.py\", line 1, in <module>\nKeyError: 'id'\n"
)
LINE_CAPABILITIES = ParserCapabilities(
    deterministic=True, parallel_safe=True, partitionable=True, partition_framing="line"
)


class _Uppercase(AsyncParser):
    def __init__(self) -> None:
        super().__init__(name="uppercase")

    @override
    async def parse(self, source: object, context: ParseContext | None = None) -> ParseResult:
        return ParseResult(events=(ParsedEvent("upper", attributes={"text": str(source).upper()}),))


@pytest.mark.parametrize(
    ("parser", "source"),
    [
        (ApplicationLogParser(), LOG),
        (JSONParser(), '{"a": [1, 2]}'),
        (PythonTracebackParser(), TRACEBACK),
        (TimestampedLogParser(), TIMESTAMPED),
        (CLIOutputParser(command="kv"), "a=1\nb=2\n"),
        (MixedContentParser(), "ERROR failed\n```json\n{}\n```\nplain words\n"),
        (DeterministicParser([RegexPattern("word", r"(?P<word>\w+)")], name="words"), "a b\n"),
        (_Uppercase(), "text"),
    ],
    ids=lambda value: type(value).__name__ if not isinstance(value, str) else "",
)
async def test_built_in_parsers_honor_the_parser_contract(
    parser: Parser[Aggregate], source: str
) -> None:
    result = await check_parser(parser, source, ParseContext(source_id="contract"))
    assert result.events


async def test_built_in_aggregators_honor_the_aggregation_contract() -> None:
    application = ApplicationLogParser()
    events = (await application.parse(LOG, ParseContext(source_id="log"))).events
    reproducible = await check_aggregator(EvidenceAggregator(reproducible=True), events)
    assert reproducible
    assert await check_aggregator(EvidenceAggregator(reproducible=False), events)
    counts = await check_aggregator(EventAggregator(group_by=("message",)), events)
    assert all(isinstance(item, CountAggregate) for item in counts)
    mixed = MixedContentParser()
    mixed_events = (await mixed.parse("ERROR failed\n{}\nplain words\n")).events
    assert await check_aggregator(mixed.aggregator, mixed_events)
    assert await check_codec(EvidenceCodec(), reproducible)


async def test_line_partitioner_honors_the_partitioning_contract() -> None:
    lines = ["first", "second ü", "third", "", "fifth"]
    partitions = await check_partitioner(
        LinePartitioner(max_lines=2), lines, capabilities=LINE_CAPABILITIES
    )
    assert [partition.start_line for partition in partitions] == [1, 3, 5]


@pytest.mark.parametrize(
    "factory",
    [AsyncExecutionBackend, ThreadExecutionBackend, ProcessExecutionBackend],
)
async def test_built_in_backends_honor_the_execution_contract(
    factory: Callable[[], ExecutionBackend],
) -> None:
    await check_execution_backend(factory())


async def test_built_in_sinks_honor_the_sink_contract() -> None:
    for sink in (
        NullObservabilitySink(),
        LoggingObservabilitySink(),
        OpenTelemetryObservabilitySink(),
        CompositeObservabilitySink([NullObservabilitySink(), LoggingObservabilitySink()]),
    ):
        await check_observability_sink(sink)


class _EchoModel(LanguageModel):
    def __init__(self, reply: object = "OK") -> None:
        self._reply = reply

    @override
    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        # pyrefly: ignore[bad-return]
        return self._reply


async def test_language_model_contract() -> None:
    assert await check_language_model(_EchoModel()) == "OK"
    for reply in ("", "  ", None):
        with pytest.raises(AssertionError, match="non-empty text"):
            await check_language_model(_EchoModel(reply))


async def test_in_memory_registry_honors_the_registry_contract() -> None:
    registry = InMemoryParserRegistry()
    await check_parser_registry(registry, [JSONParser(), ApplicationLogParser(), _Uppercase()])
    assert await registry.names() == ()


async def test_tokenizer_detector_backend_and_pattern_contracts() -> None:
    await check_tokenizer(ApproximateTokenizer())
    await check_code_detector(
        TreeSitterCodeDetector(["python"]), {"import os": "python", "plain words": None}
    )
    assert await check_command_output_backend(JcBackend(), "kv", "a=1\n") == ({"a": "1"},)
    regex = check_pattern(RegexPattern("error", r"ERROR (?P<message>.+)"), "ERROR x", "INFO x")
    assert regex.attributes == {"message": "x"}
    check_pattern(ExactPattern("ok", "ok"), "ok", "no")
    check_pattern(PredicatePattern("long", lambda value: len(str(value)) > 3), "long", "no")


async def test_parser_contract_rejects_broken_parsers() -> None:
    class Broken(_Uppercase):
        def __init__(self, **overrides: Any) -> None:
            super().__init__()
            self._overrides = overrides
            self._calls = 0

        @property
        @override
        def name(self) -> str:
            return self._overrides.get("name", "broken")

        @property
        @override
        def capabilities(self) -> ParserCapabilities:
            return self._overrides.get("capabilities", super().capabilities)

        @override
        async def parse(self, source: object, context: ParseContext | None = None) -> ParseResult:
            self._calls += 1
            if self._overrides.get("empty"):
                return ParseResult()
            if self._overrides.get("unstable"):
                return ParseResult(events=(ParsedEvent("call", attributes={"n": self._calls}),))
            return await super().parse(source, context)

    with pytest.raises(AssertionError, match="must be a Parser"):
        # pyrefly: ignore[bad-argument-type]
        await check_parser(object(), "x")
    with pytest.raises(AssertionError, match=r"parser\.name"):
        await check_parser(Broken(name=""), "x")
    with pytest.raises(AssertionError, match="ParserCapabilities"):
        await check_parser(Broken(capabilities=object()), "x")
    with pytest.raises(AssertionError, match="at least one event"):
        await check_parser(Broken(empty=True), "x")
    with pytest.raises(AssertionError, match="equal results"):
        await check_parser(
            Broken(unstable=True, capabilities=ParserCapabilities(deterministic=True)), "x"
        )


class _ListAggregator(Aggregator[CountAggregate]):
    def __init__(self, mode: str) -> None:
        self._mode = mode

    @property
    @override
    def lossless(self) -> bool:
        return self._mode == "lossless"

    @override
    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[CountAggregate, ...]:
        if isinstance(events, AsyncIterable):
            items = [event async for event in events]
            if self._mode == "stream":
                return ()
        else:
            items = list(events)
        if self._mode == "list":
            # pyrefly: ignore[bad-return]
            return [CountAggregate("x", len(items), None, None, {})]
        if self._mode == "object":
            # pyrefly: ignore[bad-return]
            return (object(),)
        return (CountAggregate("x", len(items), None, None, {}),)

    @override
    async def merge(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[CountAggregate, ...]:
        if isinstance(partials, AsyncIterable):
            items = [item async for item in partials]
            if self._mode == "merge-stream":
                return ()
        else:
            items = list(partials)
        if self._mode == "merge":
            return ()
        return tuple(item for item in items if isinstance(item, CountAggregate))

    @override
    async def materialize(
        self, aggregates: Sequence[Aggregate], events: Sequence[ParsedEvent] | None = None
    ) -> tuple[ParsedEvent, ...]:
        return ()


async def test_aggregator_contract_rejects_broken_aggregators() -> None:
    events = (ParsedEvent("x"),)
    assert await check_aggregator(_ListAggregator("ok"), events)
    cases = {
        "list": "return a tuple",
        "object": "Aggregate instances",
        "stream": "synchronous and an asynchronous stream must agree",
        "merge": "unchanged",
        "merge-stream": "merging a synchronous",
        "lossless": "rebuild exactly",
    }
    for mode, message in cases.items():
        with pytest.raises(AssertionError, match=message):
            await check_aggregator(_ListAggregator(mode), events)
    with pytest.raises(AssertionError, match="must be an Aggregator"):
        # pyrefly: ignore[bad-argument-type]
        await check_aggregator(object(), events)
    with pytest.raises(AssertionError, match="must not be empty"):
        await check_aggregator(_ListAggregator("ok"), ())


async def test_parser_contract_skips_rules_a_parser_does_not_declare() -> None:
    class Plain(_Uppercase):
        @property
        @override
        def capabilities(self) -> ParserCapabilities:
            return ParserCapabilities()

    class Counting(_Uppercase):
        @override
        def build_aggregator(self) -> Aggregator[Any]:
            return EventAggregator()

    assert await check_parser(Plain(), "x")
    assert await check_parser(Counting(), "x")


async def test_parser_contract_rejects_broken_aggregation() -> None:
    class Unstable(_Uppercase):
        def __init__(self, mode: str) -> None:
            super().__init__()
            self._mode = mode

        @override
        def build_aggregator(self) -> Aggregator[Any]:
            return _ListAggregator(self._mode)

    with pytest.raises(AssertionError, match="asynchronous stream must agree"):
        await check_parser(Unstable("stream"), "x")
    with pytest.raises(AssertionError, match="materialize must rebuild"):
        await check_parser(Unstable("lossless"), "x")


class _Codec(AggregateCodec):
    def __init__(self, mode: str = "ok", format_: str = "test") -> None:
        self._mode, self._format, self._calls = mode, format_, 0
        self._inner = EvidenceCodec()

    @property
    @override
    def format(self) -> str:
        return self._format

    @override
    async def encode(self, aggregates: Iterable[Aggregate], *, indent: int | None = None) -> str:
        self._calls += 1
        if self._mode == "bytes":
            # pyrefly: ignore[bad-return]
            return b"x"
        if self._mode == "unstable":
            return str(self._calls)
        return await self._inner.encode(aggregates, indent=indent)

    @override
    async def decode(self, data: str | bytes) -> tuple[Aggregate, ...]:
        if self._mode == "lossy":
            return ()
        if self._mode == "text-only" and isinstance(data, bytes):
            return ()
        return await self._inner.decode(data)


async def test_codec_contract_rejects_broken_codecs() -> None:
    parser = ApplicationLogParser()
    aggregates = await parser.aggregate((await parser.parse(LOG)).events)
    assert await check_codec(_Codec(), aggregates)
    cases = {
        "bytes": "return text",
        "unstable": "deterministic",
        "lossy": "decode\\(encode",
        "text-only": "UTF-8 bytes",
    }
    for mode, message in cases.items():
        with pytest.raises(AssertionError, match=message):
            await check_codec(_Codec(mode), aggregates)
    with pytest.raises(AssertionError, match=r"codec\.format"):
        await check_codec(_Codec(format_=""), aggregates)
    with pytest.raises(AssertionError, match="AggregateCodec"):
        # pyrefly: ignore[bad-argument-type]
        await check_codec(object(), aggregates)


class _Partitioner(Partitioner):
    def __init__(self, partitions: Sequence[Partition], streamed: Sequence[Partition] = ()) -> None:
        self._partitions, self._streamed = partitions, streamed

    @override
    async def partition(
        self,
        lines: Iterable[str] | AsyncIterable[str],
        *,
        source_id: str | None = None,
        capabilities: ParserCapabilities,
    ) -> AsyncIterator[Partition]:
        for partition in self._streamed if isinstance(lines, AsyncIterable) else self._partitions:
            yield partition


async def test_partitioner_contract_rejects_broken_partitioners() -> None:
    first = Partition("0", "contract", 1, 0, "a\n")
    second = Partition("1", "contract", 2, 2, "b")
    good = _Partitioner([first, second], [first, second])
    assert await check_partitioner(good, ["a", "b"], capabilities=LINE_CAPABILITIES)
    cases: dict[str, Partitioner] = {
        "at least one partition": _Partitioner([]),
        # pyrefly: ignore[bad-argument-type]
        "Partition instances": _Partitioner([object()]),
        "unique": _Partitioner([first, Partition("0", "contract", 2, 2, "b")]),
        "source_id": _Partitioner([Partition("0", "other", 1, 0, "a")]),
        "must start at line 2, byte 2": _Partitioner(
            [first, Partition("1", "contract", 3, 2, "b")]
        ),
        "partition identically": _Partitioner([first, second], [first]),
    }
    for message, partitioner in cases.items():
        with pytest.raises(AssertionError, match=message):
            await check_partitioner(partitioner, ["a", "b"], capabilities=LINE_CAPABILITIES)
    with pytest.raises(AssertionError, match="must be a Partitioner"):
        # pyrefly: ignore[bad-argument-type]
        await check_partitioner(object(), ["a"], capabilities=LINE_CAPABILITIES)
    with pytest.raises(AssertionError, match="must not be empty"):
        await check_partitioner(good, [], capabilities=LINE_CAPABILITIES)


class _Backend(AsyncExecutionBackend):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self._mode = mode

    @override
    async def run(self, function: Callable[..., Any], /, *args: object, **kwargs: object) -> Any:
        if self._mode == "swallow" and function.__name__ == "_contract_fail":
            return None
        if self._mode == "message" and function.__name__ == "_contract_fail":
            raise ValueError("other")
        if self._mode == "sync-only" and function.__name__ == "_contract_double_async":
            return function
        if self._mode == "wrong":
            return 0
        return await super().run(function, *args, **kwargs)

    @override
    # pyrefly: ignore[bad-override]
    async def map(
        self, function: Callable[[Any], Any], items: Iterable[Any], *, max_in_flight: int = 1
    ) -> AsyncIterator[Any]:
        if self._mode == "drop":
            yield 0
            return
        async for item in super().map(function, items, max_in_flight=max_in_flight):
            yield item


async def test_execution_contract_rejects_broken_backends() -> None:
    cases = {
        "wrong": "return the result",
        "sync-only": "await coroutine functions",
        "swallow": "propagate the callable's exception",
        "message": "propagate the exception",
        "drop": "one result per item",
    }
    for mode, message in cases.items():
        with pytest.raises(AssertionError, match=message):
            await check_execution_backend(_Backend(mode))
    with pytest.raises(AssertionError, match="ExecutionBackend"):
        # pyrefly: ignore[bad-argument-type]
        await check_execution_backend(object())


async def test_simple_contracts_reject_wrong_types_and_behavior() -> None:
    with pytest.raises(AssertionError, match="ObservabilitySink"):
        # pyrefly: ignore[bad-argument-type]
        await check_observability_sink(object())
    with pytest.raises(AssertionError, match="LanguageModel"):
        # pyrefly: ignore[bad-argument-type]
        await check_language_model(object())
    with pytest.raises(AssertionError, match="Tokenizer"):
        # pyrefly: ignore[bad-argument-type]
        await check_tokenizer(object())
    with pytest.raises(AssertionError, match="CodeDetector"):
        # pyrefly: ignore[bad-argument-type]
        await check_code_detector(object(), {})
    with pytest.raises(AssertionError, match="CommandOutputBackend"):
        # pyrefly: ignore[bad-argument-type]
        await check_command_output_backend(object(), "kv", "a=1")
    with pytest.raises(AssertionError, match="must be a Pattern"):
        # pyrefly: ignore[bad-argument-type]
        check_pattern(object(), "a", "b")

    class Counting(Tokenizer):
        def __init__(self, counts: Sequence[int], by_bytes: int | None = None) -> None:
            self._counts, self._by_bytes, self._last = list(counts), by_bytes, 0

        @override
        async def count(self, text: str) -> int:
            self._last = self._counts.pop(0)
            return self._last

        @override
        async def count_bytes(self, data: bytes) -> int:
            return self._by_bytes if self._by_bytes is not None else self._last

    with pytest.raises(AssertionError, match="empty text"):
        await check_tokenizer(Counting([1]))
    with pytest.raises(AssertionError, match="never shrink"):
        await check_tokenizer(Counting([0, 3, 1]), ("ab", "abc"))
    with pytest.raises(AssertionError, match="count_bytes"):
        await check_tokenizer(Counting([0, 1], by_bytes=9), ("a",))

    class Fixed(CodeDetector):
        @override
        async def detect(self, text: str) -> str | None:
            return "sql"

    with pytest.raises(AssertionError, match="expected 'python'"):
        await check_code_detector(Fixed(), {"import os": "python"})

    class Failing(JcBackend):
        @override
        async def parse(self, command: str, text: str) -> object:
            raise ValueError("unreadable")

    with pytest.raises(AssertionError, match="without issues"):
        await check_command_output_backend(Failing(), "kv", "a=1")


async def test_command_output_backend_contract_rejects_unnamed_backends() -> None:
    class Unnamed(JcBackend):
        @property
        @override
        def name(self) -> str:
            return ""

    with pytest.raises(AssertionError, match=r"backend\.name"):
        await check_command_output_backend(Unnamed(), "kv", "a=1")


def test_pattern_contract_rejects_broken_patterns() -> None:
    class Odd(RegexPattern):
        def __init__(self, mode: str) -> None:
            super().__init__("odd", r"(?P<value>\w+)")
            self._mode, self._calls = mode, 0

        @property
        @override
        def priority(self) -> int:
            # pyrefly: ignore[bad-return]
            return "high" if self._mode == "priority" else 0

        @override
        def match(self, value: object) -> PatternMatch | None:
            self._calls += 1
            if self._mode == "never":
                return None
            if self._mode == "unstable":
                return PatternMatch(attributes={"call": self._calls})
            return super().match(value)

        @override
        def to_event(self, match: PatternMatch) -> ParsedEvent:
            if self._mode == "event":
                return ParsedEvent("other")
            return super().to_event(match)

    cases = {
        "priority": "integer",
        "never": "PatternMatch for a match",
        "unstable": "deterministic",
        "event": "event type",
        "ok": "None for a non-match",
    }
    for mode, message in cases.items():
        with pytest.raises(AssertionError, match=message):
            check_pattern(Odd(mode), "word", "other")


async def test_registry_contract_rejects_broken_registries() -> None:
    parsers = [JSONParser(), ApplicationLogParser()]

    class Loose(InMemoryParserRegistry):
        def __init__(self, mode: str) -> None:
            super().__init__()
            self._mode = mode

        @override
        async def register_all(
            self, parsers: Iterable[Parser[Aggregate]], *, replace: bool = False
        ) -> None:
            items = list(parsers)
            if self._mode == "partial" and len(items) > 1:
                await super().register_all(items[:1], replace=replace)
            await super().register_all(items, replace=replace or self._mode == "replace")

        @override
        async def names(self) -> tuple[str, ...]:
            names = await super().names()
            return tuple(reversed(names)) if self._mode == "unsorted" else names

        @override
        async def get(self, name: str) -> Parser[Aggregate]:
            if self._mode == "copy":
                return JSONParser()
            if self._mode == "forgiving" and name not in await super().names():
                return JSONParser()
            return await super().get(name)

        @override
        async def unregister(self, name: str) -> Parser[Aggregate]:
            parser = await super().unregister(name)
            return JSONParser() if self._mode == "unregister" else parser

    cases = {
        "replace": "DuplicateParserError",
        "partial": "must not register any parser",
        "unsorted": "sorted",
        "copy": "get must return the parser",
        "unregister": "return the removed parser",
        "forgiving": "RegistryError",
    }
    for mode, message in cases.items():
        with pytest.raises(AssertionError, match=message):
            await check_parser_registry(Loose(mode), parsers)
    with pytest.raises(AssertionError, match="ParserRegistry"):
        # pyrefly: ignore[bad-argument-type]
        await check_parser_registry(object(), parsers)
    with pytest.raises(AssertionError, match="two distinct names"):
        await check_parser_registry(InMemoryParserRegistry(), [JSONParser(), JSONParser()])
    registry: ParserRegistry = InMemoryParserRegistry()
    await registry.register(_Uppercase())
    with pytest.raises(AssertionError, match="start empty"):
        await check_parser_registry(registry, parsers)


async def test_json_codec_contract() -> None:
    await check_json_codec(StrictJSONCodec())

    class Lenient(StrictJSONCodec):
        @override
        async def decode(self, text: str) -> Any:
            try:
                return await super().decode(text)
            except ValueError:
                return None

    class Lossy(StrictJSONCodec):
        @override
        async def decode(self, text: str) -> Any:
            value = await super().decode(text)
            return float(value) if isinstance(value, int) else value

    with pytest.raises(AssertionError, match="must raise ValueError"):
        await check_json_codec(Lenient())
    with pytest.raises(AssertionError, match=r"returned 1\.2345"):
        await check_json_codec(Lossy())
    with pytest.raises(AssertionError, match="must be a JSONCodec"):
        # pyrefly: ignore[bad-argument-type]
        await check_json_codec(object())
