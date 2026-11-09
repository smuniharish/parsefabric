"""Pluggable components: sinks, codecs, partitioners and executor backends."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from parsefabric import ParseEngine
from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    CommandOutputBackend,
    JcBackend,
    JSONParser,
)
from parsefabric.codecs import AggregateCodec, EvidenceCodec, JSONCodec, StrictJSONCodec
from parsefabric.execution import AsyncExecutionBackend, ExecutorBackend
from parsefabric.observability import (
    CompositeObservabilitySink,
    LifecycleEvent,
    NullObservabilitySink,
    ObservabilitySink,
    publish,
)
from parsefabric.partitioning import LinePartitioner
from parsefabric.registry import ParserRegistry
from tests.support.aio import collect

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

    from parsefabric.aggregation import Aggregate


class RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.names: list[str] = []
        self.flushed = 0
        self.closed = 0

    async def emit(self, event: LifecycleEvent) -> None:
        self.names.append(event.name)

    async def flush(self) -> None:
        self.flushed += 1

    async def close(self) -> None:
        self.closed += 1


class BrokenSink(ObservabilitySink):
    async def emit(self, event: LifecycleEvent) -> None:
        raise RuntimeError(f"cannot record {event.name}")

    async def flush(self) -> None:
        raise RuntimeError("flush failed")

    async def close(self) -> None:
        raise RuntimeError("close failed")


async def test_sink_failures_are_logged_and_never_break_the_operation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = RecordingSink()
    composite = CompositeObservabilitySink([BrokenSink(), recorder])
    assert composite.sinks[1] is recorder
    with caplog.at_level(logging.ERROR, logger="parsefabric.observability"):
        result = await ParseEngine(composite).parse(ApplicationLogParser(), "db timeout")
    assert result.events
    assert recorder.names[:2] == ["ParserSelected", "ParseStarted"]
    assert "BrokenSink failed on ParserSelected" in caplog.text
    await publish(NullObservabilitySink(), LifecycleEvent("ParseStarted"))
    await NullObservabilitySink().emit(LifecycleEvent("ParseStarted"))


async def test_composite_flushes_and_closes_every_child_before_raising() -> None:
    first, last = RecordingSink(), RecordingSink()
    healthy = CompositeObservabilitySink([first, last])
    await healthy.flush()
    await healthy.close()
    assert (first.flushed, first.closed, last.flushed, last.closed) == (1, 1, 1, 1)

    composite = CompositeObservabilitySink([first, BrokenSink(), last])
    with pytest.raises(ExceptionGroup, match="1 observability sink") as flushed:
        await composite.flush()
    assert flushed.group_contains(RuntimeError, match="flush failed")
    with pytest.raises(ExceptionGroup, match="failed to close"):
        await composite.close()
    assert (first.closed, last.closed) == (2, 2)
    with pytest.raises(TypeError, match="ObservabilitySink"):
        # pyrefly: ignore[bad-argument-type]
        CompositeObservabilitySink([object()])


class UpperCodec(AggregateCodec):
    """Wraps the evidence codec to prove the engine delegates to its codec."""

    def __init__(self) -> None:
        self._inner = EvidenceCodec()

    @property
    def format(self) -> str:
        return "test.upper/1"

    async def encode(self, aggregates: Iterable[Aggregate], *, indent: int | None = None) -> str:
        return (await self._inner.encode(aggregates, indent=indent)).upper()

    async def decode(self, data: str | bytes) -> tuple[Aggregate, ...]:
        raise NotImplementedError(data)


async def test_engine_uses_and_validates_its_components() -> None:
    sink, codec = RecordingSink(), UpperCodec()
    engine = ParseEngine(sink, codec=codec)
    assert (engine.sink, engine.codec) == (sink, codec)
    assert isinstance(ParseEngine().codec, EvidenceCodec)
    parser = ApplicationLogParser()
    aggregates = await engine.aggregate(parser, (await engine.parse(parser, "x")).events)
    assert (await engine.serialize(aggregates)).startswith('{"FORMAT":"PARSEFABRIC.')
    with pytest.raises(NotImplementedError):
        await engine.deserialize("{}")
    with pytest.raises(TypeError, match="ObservabilitySink"):
        # pyrefly: ignore[bad-argument-type]
        ParseEngine(object())
    with pytest.raises(TypeError, match="AggregateCodec"):
        # pyrefly: ignore[bad-argument-type]
        ParseEngine(codec=object())


async def test_cancelled_aggregation_and_materialization_are_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = RecordingSink()
    engine = ParseEngine(sink)
    parser = ApplicationLogParser()
    events = (await engine.parse(parser, "db timeout")).events
    aggregates = await engine.aggregate(parser, events)
    aggregator = type(parser.aggregator)

    async def cancelled(*args: Any, **kwargs: Any) -> Any:
        raise asyncio.CancelledError

    monkeypatch.setattr(aggregator, "aggregate", cancelled)
    monkeypatch.setattr(aggregator, "materialize", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await engine.aggregate(parser, events)
    with pytest.raises(asyncio.CancelledError):
        await engine.materialize(parser, "db timeout", aggregates)
    assert "AggregationCancelled" in sink.names
    assert sink.names[-1] == "MaterializeCancelled"


class ShoutingJSONCodec(JSONCodec):
    async def decode(self, text: str) -> object:
        value = await StrictJSONCodec().decode(text)
        return {"shouted": value}


async def test_json_parser_decodes_with_its_codec() -> None:
    codec = ShoutingJSONCodec()
    parser = JSONParser(codec=codec)
    assert parser.codec is codec
    assert isinstance(JSONParser().codec, StrictJSONCodec)
    result = await parser.parse('{"status": "ok"}')
    assert result.events[0].attributes["value"] == {"shouted": {"status": "ok"}}
    with pytest.raises(TypeError, match="JSONCodec"):
        # pyrefly: ignore[bad-argument-type]
        JSONParser(codec="json")


async def _lines(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        await asyncio.sleep(0)
        yield line


async def test_partitioner_reads_async_sources_and_reports_partitions() -> None:
    sink = RecordingSink()
    partitioner = LinePartitioner(max_lines=2, sink=sink)
    partitions = await collect(
        partitioner.partition(
            _lines("one\n", "two\n", "three"),
            source_id="stream",
            capabilities=ApplicationLogParser().capabilities,
        )
    )
    assert [partition.content for partition in partitions] == ["one\ntwo\n", "three"]
    assert sink.names == ["PartitionCreated", "PartitionCreated"]
    with pytest.raises(TypeError, match="ObservabilitySink"):
        # pyrefly: ignore[bad-argument-type]
        LinePartitioner(sink=object())


def _double(value: int) -> int:
    return value * 2


async def test_backends_map_async_sources_and_publish_events() -> None:
    sink = RecordingSink()
    async with AsyncExecutionBackend(sink=sink) as backend:
        assert backend.sink is sink
        doubled = [item async for item in backend.map(_double, _numbers(3))]
        await backend.emit("ExecutionStarted", error_type="custom")
    assert sorted(doubled) == [0, 2, 4]
    assert sink.names.count("ExecutionCompleted") == 3
    assert sink.names[-1] == "ExecutionStarted"

    with ThreadPoolExecutor(max_workers=1) as pool:
        async with ExecutorBackend(pool) as backend:
            assert await backend.run(_double, 21) == 42
    with pytest.raises(TypeError, match="Executor"):
        # pyrefly: ignore[bad-argument-type]
        ExecutorBackend(object())
    with pytest.raises(TypeError, match="ObservabilitySink"):
        # pyrefly: ignore[bad-argument-type]
        AsyncExecutionBackend(sink=object())


async def _numbers(count: int) -> AsyncIterator[int]:
    for value in range(count):
        await asyncio.sleep(0)
        yield value


class SnapshotRegistry(ParserRegistry):
    """A registry that stores parsers in an external mapping."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def register_all(self, parsers: Iterable[Any], *, replace: bool = False) -> None:
        self.store.update((parser.name, parser) for parser in parsers)

    async def unregister(self, name: str) -> Any:
        return self.store.pop(name)

    async def get(self, name: str) -> Any:
        return self.store[name]

    async def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.store))


async def test_custom_registries_inherit_registration_metadata_and_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from parsefabric import registry as module

    class EntryPoint:
        name = "json"

        @staticmethod
        def load() -> Any:
            return JSONParser

    monkeypatch.setattr(module, "entry_points", lambda group: [EntryPoint()])
    registry = SnapshotRegistry()
    await registry.register(ApplicationLogParser())
    assert await registry.discover() == ("json",)
    assert await registry.names() == ("application-log", "json")
    assert (await registry.metadata("json")).parser_type == "JSONParser"
    assert isinstance(await registry.unregister("json"), JSONParser)


class KeyValueBackend(CommandOutputBackend):
    """Parses ``key=value`` lines of the ``env`` command."""

    @property
    def name(self) -> str:
        return "kv-lines"

    def validate(self, command: str) -> None:
        if command != "env":
            raise ValueError(f"unsupported command {command!r}")

    async def parse(self, command: str, text: str) -> object:
        if "=" not in text:
            raise ValueError("no assignments")
        return [dict([line.split("=", 1)]) for line in text.splitlines() if line]


async def test_command_output_parsers_use_custom_backends() -> None:
    backend = KeyValueBackend()
    parser = CLIOutputParser(command="env", backend=backend)
    assert parser.backend is backend
    assert CLIOutputParser(command="kv").backend.name == JcBackend().name == "jc"
    result = await ParseEngine().parse(parser, "HOME=/root\nSHELL=/bin/sh\n")
    assert [event.attributes for event in result.events] == [
        {"HOME": "/root"},
        {"SHELL": "/bin/sh"},
    ]
    failed = await ParseEngine().parse(parser, "garbage")
    assert [event.event_type for event in failed.events] == ["unparsed"]
    assert failed.errors[0].message == "no assignments"
    with pytest.raises(ValueError, match="unsupported"):
        CLIOutputParser(command="df", backend=backend)
    with pytest.raises(TypeError, match="CommandOutputBackend"):
        # pyrefly: ignore[bad-argument-type]
        CLIOutputParser(command="df", backend=object())
