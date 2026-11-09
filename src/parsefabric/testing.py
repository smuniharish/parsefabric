"""Contract checks for your own implementations of ParseFabric's extension points.

Every extension point is an abstract base class. These checks exercise the
behavior the rest of ParseFabric relies on, so a subclass that passes them
can be dropped into the engine, a partitioned run or an execution backend.
They are plain coroutines that raise `AssertionError` with a description of
the first broken rule, so they work with any test runner:

```python
async def test_my_parser_honors_the_parser_contract() -> None:
    await check_parser(MyParser(), "2026-01-01 ERROR disk full")
```

The built-in implementations pass every check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from parsefabric.aggregation import Aggregate, Aggregator
from parsefabric.builtins.cli_output import CLIOutputParser, CommandOutputBackend
from parsefabric.builtins.code_detection import CodeDetector
from parsefabric.capabilities import ParserCapabilities
from parsefabric.codecs import AggregateCodec, JSONCodec
from parsefabric.compression import Tokenizer
from parsefabric.engine import ParseEngine
from parsefabric.errors import DuplicateParserError, RegistryError
from parsefabric.execution import ExecutionBackend
from parsefabric.llm import ChatMessage, LanguageModel
from parsefabric.models import ParseContext, ParsedEvent, ParseResult
from parsefabric.observability import LifecycleEvent, ObservabilitySink
from parsefabric.parser import Parser
from parsefabric.partitioning import Partition, Partitioner
from parsefabric.patterns import Pattern, PatternMatch
from parsefabric.registry import ParserRegistry
from parsefabric.serialization import dumps_result, loads_result

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Mapping, Sequence

    from parsefabric.models import JSONValue

__all__ = [
    "check_aggregator",
    "check_code_detector",
    "check_codec",
    "check_command_output_backend",
    "check_execution_backend",
    "check_json_codec",
    "check_language_model",
    "check_observability_sink",
    "check_parser",
    "check_parser_registry",
    "check_partitioner",
    "check_pattern",
    "check_tokenizer",
]


def _require(condition: object, message: str) -> None:
    # Explicit raise: ``assert`` statements disappear under ``python -O``.
    if not condition:
        raise AssertionError(message)


def _require_name(value: object, what: str) -> None:
    _require(isinstance(value, str) and value, f"{what} must be a non-empty string")


async def _stream[T](items: Iterable[T]) -> AsyncIterator[T]:
    for item in items:
        yield item


async def check_parser(
    parser: Parser[Aggregate],
    source: object,
    context: ParseContext | None = None,
) -> ParseResult:
    """Check a `Parser` subclass against the parser contract.

    The parser must declare a name, version and `ParserCapabilities`, return
    a `ParseResult` that survives a JSON round trip, return equal results for
    equal input when it declares itself deterministic, and, when it declares
    itself aggregatable, aggregate its events identically from synchronous
    and asynchronous streams and materialize them back when its aggregator
    is lossless.

    Args:
        parser: The parser to check.
        source: A representative input that produces at least one event.
        context: The context to parse ``source`` with.

    Returns:
        The engine's result for ``source``, for further assertions.

    Raises:
        AssertionError: If the parser breaks the contract.
    """
    _require(isinstance(parser, Parser), "parser must be a Parser")
    _require_name(parser.name, "parser.name")
    _require_name(parser.version, "parser.version")
    capabilities = parser.capabilities
    _require(
        isinstance(capabilities, ParserCapabilities),
        "parser.capabilities must be a ParserCapabilities",
    )
    engine = ParseEngine()
    result = await engine.parse(parser, source, context)
    _require(isinstance(result, ParseResult), "parse must return a ParseResult")
    _require(result.events, "the sample source must produce at least one event")
    _require(
        loads_result(dumps_result(result)) == result,
        "the result must survive a JSON round trip unchanged",
    )
    if capabilities.deterministic:
        _require(
            await engine.parse(parser, source, context) == result,
            "a deterministic parser must return equal results for equal input",
        )
    if capabilities.aggregatable:
        aggregates = await engine.aggregate(parser, result.events)
        _require(
            await parser.aggregate(_stream(result.events)) == aggregates,
            "aggregating a synchronous and an asynchronous stream must agree",
        )
        if parser.aggregator.lossless:
            restored = await engine.materialize(parser, source, aggregates, context)
            _require(
                restored == result.events,
                "materialize must rebuild exactly the parsed events",
            )
    return result


async def check_aggregator[AggregateT: Aggregate](
    aggregator: Aggregator[AggregateT],
    events: Sequence[ParsedEvent],
) -> tuple[AggregateT, ...]:
    """Check an `Aggregator` subclass against the aggregation contract.

    Aggregating synchronous and asynchronous streams must agree, merging a
    complete set of aggregates must return them unchanged, and a lossless
    aggregator must materialize exactly the original events.

    Args:
        aggregator: The aggregator to check.
        events: Events of one source document, in source order, as a parser
            produced them.

    Returns:
        The aggregates of ``events``.

    Raises:
        AssertionError: If the aggregator breaks the contract.
    """
    _require(isinstance(aggregator, Aggregator), "aggregator must be an Aggregator")
    _require(events, "events must not be empty")
    aggregates = await aggregator.aggregate(events)
    _require(isinstance(aggregates, tuple), "aggregate must return a tuple")
    _require(
        all(isinstance(item, Aggregate) for item in aggregates),
        "aggregate must return Aggregate instances",
    )
    _require(
        await aggregator.aggregate(_stream(events)) == aggregates,
        "aggregating a synchronous and an asynchronous stream must agree",
    )
    _require(
        await aggregator.merge(aggregates) == aggregates,
        "merging a complete set of aggregates must return them unchanged",
    )
    _require(
        await aggregator.merge(_stream(aggregates)) == aggregates,
        "merging a synchronous and an asynchronous stream must agree",
    )
    if aggregator.lossless:
        restored = await aggregator.materialize(
            aggregates, events if aggregator.requires_source else None
        )
        _require(restored == tuple(events), "materialize must rebuild exactly the events")
    return aggregates


async def check_codec(codec: AggregateCodec, aggregates: Sequence[Aggregate]) -> str:
    """Check an `AggregateCodec` subclass against the codec contract.

    Encoding then decoding, from text or UTF-8 bytes, must return equal
    aggregates, and encoding must be deterministic.

    Args:
        codec: The codec to check.
        aggregates: Aggregates the codec supports.

    Returns:
        The encoded document.

    Raises:
        AssertionError: If the codec breaks the contract.
    """
    _require(isinstance(codec, AggregateCodec), "codec must be an AggregateCodec")
    _require_name(codec.format, "codec.format")
    encoded = await codec.encode(aggregates)
    _require(isinstance(encoded, str), "encode must return text")
    _require(await codec.encode(aggregates) == encoded, "encode must be deterministic")
    expected = tuple(aggregates)
    _require(await codec.decode(encoded) == expected, "decode(encode(x)) must equal x")
    _require(
        await codec.decode(encoded.encode("utf-8")) == expected,
        "decode must accept the encoded document as UTF-8 bytes",
    )
    return encoded


_JSON_SAMPLES: tuple[tuple[str, JSONValue], ...] = (
    ('{"a": [1, 2.5, true, null], "b": "\\u00fc"}', {"a": [1, 2.5, True, None], "b": "\u00fc"}),
    ("[]", []),
    ('"text"', "text"),
    ("12345678901234567890", 12345678901234567890),
)
_INVALID_JSON: tuple[str, ...] = ("", "{", '{"a": 1,}', "[1] [2]", "{'a': 1}")


async def check_json_codec(codec: JSONCodec) -> None:
    """Check a `JSONCodec` subclass against the JSON codec contract.

    Valid documents must decode to the standard JSON values, with integers
    kept exact, and malformed documents must raise `ValueError`.

    Args:
        codec: The codec to check.

    Raises:
        AssertionError: If the codec breaks the contract.
    """
    _require(isinstance(codec, JSONCodec), "codec must be a JSONCodec")
    for text, expected in _JSON_SAMPLES:
        decoded = await codec.decode(text)
        _require(decoded == expected, f"decode({text!r}) returned {decoded!r}")
    for text in _INVALID_JSON:
        try:
            await codec.decode(text)
        except ValueError:
            continue
        raise AssertionError(f"decode({text!r}) must raise ValueError")


async def check_partitioner(
    partitioner: Partitioner,
    lines: Sequence[str],
    *,
    capabilities: ParserCapabilities,
    source_id: str | None = "contract",
) -> tuple[Partition, ...]:
    """Check a `Partitioner` subclass against the partitioning contract.

    Partitions must be yielded in source order with unique identifiers and
    the given ``source_id``, start at line 1 and byte 0, and be contiguous:
    each partition starts where the previous one ends, in lines and in UTF-8
    bytes. Synchronous and asynchronous input must partition identically.

    Args:
        partitioner: The partitioner to check.
        lines: A document's records, at least one.
        capabilities: Capabilities of a parser the partitioner accepts.
        source_id: Source identifier to copy into the partitions.

    Returns:
        The partitions.

    Raises:
        AssertionError: If the partitioner breaks the contract.
    """
    _require(isinstance(partitioner, Partitioner), "partitioner must be a Partitioner")
    _require(lines, "lines must not be empty")
    partitions = tuple(
        [
            partition
            async for partition in partitioner.partition(
                lines, source_id=source_id, capabilities=capabilities
            )
        ]
    )
    _require(partitions, "a non-empty document must produce at least one partition")
    _require(
        all(isinstance(partition, Partition) for partition in partitions),
        "partition must yield Partition instances",
    )
    _require(
        len({partition.partition_id for partition in partitions}) == len(partitions),
        "partition identifiers must be unique",
    )
    _require(
        all(partition.source_id == source_id for partition in partitions),
        "partitions must carry the given source_id",
    )
    line, offset = 1, 0
    for partition in partitions:
        _require(
            (partition.start_line, partition.start_offset) == (line, offset),
            f"partition {partition.partition_id} must start at line {line}, byte {offset}",
        )
        line += len(partition.content.splitlines())
        offset += len(partition.content.encode("utf-8"))
    from_stream = tuple(
        [
            partition
            async for partition in partitioner.partition(
                _stream(lines), source_id=source_id, capabilities=capabilities
            )
        ]
    )
    _require(
        from_stream == partitions,
        "synchronous and asynchronous input must partition identically",
    )
    return partitions


def _contract_double(value: int) -> int:
    return value * 2


async def _contract_double_async(value: int) -> int:
    return value * 2


def _contract_fail(value: int) -> int:
    raise ValueError(f"contract failure {value}")


async def check_execution_backend(backend: ExecutionBackend) -> None:
    """Check an `ExecutionBackend` subclass against the execution contract.

    The backend must run synchronous and asynchronous module-level
    callables, propagate their exceptions, map every item exactly once, and
    shut down idempotently. The check shuts the backend down at the end.

    Args:
        backend: The backend to check. Process and cluster backends must be
            able to import ``parsefabric.testing`` in their workers.

    Raises:
        AssertionError: If the backend breaks the contract.
    """
    _require(isinstance(backend, ExecutionBackend), "backend must be an ExecutionBackend")
    async with backend:
        _require(await backend.run(_contract_double, 21) == 42, "run must return the result")
        _require(
            await backend.run(_contract_double_async, 21) == 42,
            "run must await coroutine functions",
        )
        try:
            await backend.run(_contract_fail, 1)
        except ValueError as error:
            _require(str(error) == "contract failure 1", "run must propagate the exception")
        else:
            raise AssertionError("run must propagate the callable's exception")
        mapped = [item async for item in backend.map(_contract_double, range(8), max_in_flight=3)]
        _require(
            sorted(mapped) == [value * 2 for value in range(8)],
            "map must return one result per item",
        )
    await backend.shutdown()


async def check_observability_sink(sink: ObservabilitySink) -> None:
    """Check an `ObservabilitySink` subclass against the sink contract.

    The sink must accept lifecycle events with and without attributes, and
    flush and close without raising. The check closes the sink at the end.

    Args:
        sink: The sink to check.

    Raises:
        AssertionError: If ``sink`` is not an `ObservabilitySink`.
        Exception: Whatever the sink raises; sinks must not raise.
    """
    _require(isinstance(sink, ObservabilitySink), "sink must be an ObservabilitySink")
    await sink.emit(LifecycleEvent("ParseStarted", parser_name="contract"))
    await sink.emit(
        LifecycleEvent(
            "ParseCompleted",
            parser_name="contract",
            partition_id="0",
            attributes={"event_count": 1, "ratio": 0.5, "ok": True, "label": "x"},
        )
    )
    await sink.flush()
    await sink.close()


async def check_language_model(model: LanguageModel) -> str:
    """Check a `LanguageModel` subclass against the model contract.

    The model must complete a system and user conversation with text.

    Args:
        model: The model to check. Live models are called once.

    Returns:
        The completion.

    Raises:
        AssertionError: If the model breaks the contract.
    """
    _require(isinstance(model, LanguageModel), "model must be a LanguageModel")
    reply = await model.complete(
        (
            ChatMessage("system", "You are a contract check. Answer briefly."),
            ChatMessage("user", "Reply with the word OK."),
        )
    )
    _require(isinstance(reply, str) and reply.strip(), "complete must return non-empty text")
    return reply


async def check_parser_registry(
    registry: ParserRegistry,
    parsers: Sequence[Parser[Aggregate]],
) -> None:
    """Check a `ParserRegistry` subclass against the registry contract.

    Registration must be atomic, reject duplicates unless replacing, list
    names in sorted order, return the registered objects, and unregister.
    The check leaves the registry empty.

    Args:
        registry: An empty registry.
        parsers: At least two parsers with distinct names.

    Raises:
        AssertionError: If the registry breaks the contract.
    """
    _require(isinstance(registry, ParserRegistry), "registry must be a ParserRegistry")
    names = sorted(parser.name for parser in parsers)
    _require(
        len(names) >= 2 and len(set(names)) == len(names),
        "parsers must hold at least two distinct names",
    )
    _require(await registry.names() == (), "the registry must start empty")
    first, *rest = parsers
    await registry.register(first)
    try:
        await registry.register_all([*rest, first])
    except DuplicateParserError:
        pass
    else:
        raise AssertionError("registering a taken name must raise DuplicateParserError")
    _require(
        await registry.names() == (first.name,),
        "a failed register_all must not register any parser",
    )
    await registry.register_all(rest)
    _require(await registry.names() == tuple(names), "names must be sorted")
    for parser in parsers:
        _require(await registry.get(parser.name) is parser, "get must return the parser")
    await registry.register(first, replace=True)
    _require(await registry.get(first.name) is first, "replace must keep the new parser")
    metadata = await registry.metadata(first.name)
    _require(
        (metadata.name, metadata.version) == (first.name, first.version),
        "metadata must describe the registered parser",
    )
    for parser in parsers:
        _require(
            await registry.unregister(parser.name) is parser,
            "unregister must return the removed parser",
        )
    try:
        await registry.get(first.name)
    except RegistryError:
        pass
    else:
        raise AssertionError("get of an unknown name must raise RegistryError")
    _require(await registry.names() == (), "unregister must remove every parser")


async def check_tokenizer(
    tokenizer: Tokenizer, samples: Sequence[str] = ("", "a", "ab cd")
) -> None:
    """Check a `Tokenizer` subclass against the tokenizer contract.

    Counts must be non-negative integers, zero for empty text, monotonic
    when text is appended to, and equal for text and its UTF-8 bytes.

    Args:
        tokenizer: The tokenizer to check.
        samples: Texts to count, each a prefix of the next.

    Raises:
        AssertionError: If the tokenizer breaks the contract.
    """
    _require(isinstance(tokenizer, Tokenizer), "tokenizer must be a Tokenizer")
    _require(await tokenizer.count("") == 0, "empty text must count zero tokens")
    previous = 0
    for text in samples:
        count = await tokenizer.count(text)
        _require(
            type(count) is int and count >= previous,
            "counts must be integers that never shrink when text is appended",
        )
        _require(
            await tokenizer.count_bytes(text.encode("utf-8")) == count,
            "count_bytes must agree with count for UTF-8 text",
        )
        previous = count


async def check_code_detector(
    detector: CodeDetector,
    expected: Mapping[str, str | None],
) -> None:
    """Check a `CodeDetector` subclass against the detector contract.

    Detection must return the expected language, or ``None`` for text that
    is not code, and repeat the same answer for the same text.

    Args:
        detector: The detector to check.
        expected: Sample texts and the language each must be detected as.

    Raises:
        AssertionError: If the detector breaks the contract.
    """
    _require(isinstance(detector, CodeDetector), "detector must be a CodeDetector")
    for text, language in expected.items():
        for _ in range(2):
            detected = await detector.detect(text)
            _require(
                detected == language,
                f"detect({text!r}) returned {detected!r}, expected {language!r}",
            )


async def check_command_output_backend(
    backend: CommandOutputBackend,
    command: str,
    output: str,
) -> tuple[dict[str, JSONValue], ...]:
    """Check a `CommandOutputBackend` subclass against the backend contract.

    The backend must name itself, accept ``command``, and turn ``output``
    into JSON records that `CLIOutputParser` reports without issues.

    Args:
        backend: The backend to check.
        command: A command the backend supports.
        output: Representative output of ``command`` with at least one record.

    Returns:
        The records, as event attributes.

    Raises:
        AssertionError: If the backend breaks the contract.
    """
    _require(isinstance(backend, CommandOutputBackend), "backend must be a CommandOutputBackend")
    _require_name(backend.name, "backend.name")
    backend.validate(command)
    result = await check_parser(CLIOutputParser(command=command, backend=backend), output)
    _require(not result.errors, f"the output must parse without issues: {result.errors}")
    return tuple(event.attributes for event in result.events)


def check_pattern(pattern: Pattern, matching: object, other: object) -> PatternMatch:
    """Check a `Pattern` subclass against the pattern contract.

    The pattern must describe itself, match ``matching`` with the same
    result every time, turn the match into an event of its event type, and
    not match ``other``.

    Args:
        pattern: The pattern to check.
        matching: A value the pattern must match.
        other: A value the pattern must not match.

    Returns:
        The match of ``matching``.

    Raises:
        AssertionError: If the pattern breaks the contract.
    """
    _require(isinstance(pattern, Pattern), "pattern must be a Pattern")
    _require_name(pattern.name, "pattern.name")
    _require_name(pattern.event_type, "pattern.event_type")
    _require(type(pattern.priority) is int, "pattern.priority must be an integer")
    match = pattern.match(matching)
    if not isinstance(match, PatternMatch):
        raise AssertionError("match must return a PatternMatch for a match")
    _require(pattern.match(matching) == match, "match must be deterministic")
    event = pattern.to_event(match)
    _require(
        isinstance(event, ParsedEvent) and event.event_type == pattern.event_type,
        "to_event must return an event of the pattern's event type",
    )
    _require(pattern.match(other) is None, "match must return None for a non-match")
    return match
