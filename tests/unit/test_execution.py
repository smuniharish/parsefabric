import asyncio
import gc
import multiprocessing
import time

import pytest

from parsefabric.builtins import ApplicationLogParser
from parsefabric.execution import (
    AsyncExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.observability import (
    LifecycleEvent,
    ObservabilitySink,
    OpenTelemetryObservabilitySink,
)
from parsefabric.parser import Parser


class RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.events: list[LifecycleEvent] = []

    def emit(self, event: LifecycleEvent) -> None:
        self.events.append(event)


def _square(value: int) -> int:
    return value * value


def _parse_in_worker(parser: Parser, text: str) -> str:
    return asyncio.run(parser.parse(text)).events[0].event_type


def _slow_value(delay: float) -> str:
    time.sleep(delay)
    return "done"


def _raise_worker_error() -> None:
    raise ValueError("worker failed")


def _worker_start_method() -> str | None:
    return multiprocessing.get_start_method()


async def _double(value: int) -> int:
    return value * 2


def _slow_double(value: int) -> int:
    time.sleep(0.001)
    return value * 2


async def test_async_backend_awaits_async_callables() -> None:
    backend = AsyncExecutionBackend()
    assert await backend.run(_double, 4) == 8
    await backend.shutdown()


async def test_execution_map_bounds_and_streams_results() -> None:
    async with ThreadExecutionBackend(max_workers=3) as backend:
        results = [
            result
            async for result in backend.map(
                _slow_double,
                range(12),
                max_in_flight=3,
            )
        ]
    assert sorted(results) == [value * 2 for value in range(12)]


async def test_execution_map_observes_other_completed_failures_on_abort() -> None:
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    messages: list[str] = []
    sink = RecordingSink()

    def record_exception(
        loop: asyncio.AbstractEventLoop, context: dict[str, object]
    ) -> None:
        messages.append(str(context["message"]))

    async def fail(value: int) -> int:
        raise ValueError(f"failure {value}")

    loop.set_exception_handler(record_exception)
    try:
        async with AsyncExecutionBackend(sink) as backend:
            try:
                async for _ in backend.map(fail, range(2), max_in_flight=2):
                    raise AssertionError("failed work must not produce a result")
            except ValueError:
                pass
            else:
                raise AssertionError("worker failure was not propagated")
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
        assert not messages
        assert [event.name for event in sink.events].count("ExecutionFailed") == 2
    finally:
        loop.set_exception_handler(previous_handler)


async def test_thread_backend_runs_sync_callable() -> None:
    async with ThreadExecutionBackend(max_workers=2) as backend:
        assert await backend.run(_square, 5) == 25


async def test_process_backend_serializes_top_level_callables() -> None:
    async with ProcessExecutionBackend(max_workers=1) as backend:
        assert await backend.run(_square, 6) == 36
        assert (
            await backend.run(_parse_in_worker, ApplicationLogParser(), "timeout")
            == "timeout"
        )


async def test_process_backend_uses_spawn_even_with_active_threads() -> None:
    async with ThreadExecutionBackend(max_workers=1) as threads:
        thread_work = asyncio.create_task(threads.run(_slow_value, 1))
        try:
            await asyncio.sleep(0.05)
            async with ProcessExecutionBackend(max_workers=1) as processes:
                assert await processes.run(_worker_start_method) == "spawn"
        finally:
            assert await thread_work == "done"


async def test_execution_lifecycle_and_failure_propagation() -> None:
    sink = RecordingSink()
    backend = ThreadExecutionBackend(max_workers=1, sink=sink)
    try:
        assert await backend.run(_square, 2) == 4

        def fail() -> None:
            raise RuntimeError("expected")

        with pytest.raises(RuntimeError, match=r"^expected$"):
            await backend.run(fail)
    finally:
        await backend.shutdown()
    assert [event.name for event in sink.events] == [
        "ExecutionSubmitted",
        "ExecutionStarted",
        "ExecutionCompleted",
        "ExecutionSubmitted",
        "ExecutionStarted",
        "ExecutionFailed",
    ]


async def test_async_execution_timeout_is_cancellation() -> None:
    sink = RecordingSink()
    backend = AsyncExecutionBackend(sink)
    try:
        async with asyncio.timeout(0.01):
            await backend.run(asyncio.sleep, 1)
    except TimeoutError:
        pass
    else:
        raise AssertionError("async execution timeout did not fire")
    assert [event.name for event in sink.events][-1] == "ExecutionCancelled"


async def test_process_worker_failure_and_cancellation_propagate() -> None:
    sink = RecordingSink()
    backend = ProcessExecutionBackend(max_workers=1, sink=sink)
    try:
        with pytest.raises(ValueError, match=r"^worker failed$"):
            await backend.run(_raise_worker_error)

        task = asyncio.create_task(backend.run(_slow_value, 0.1))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("process execution cancellation was not propagated")
    finally:
        await backend.shutdown()
    assert "ExecutionFailed" in [event.name for event in sink.events]
    assert "ExecutionCancelled" in [event.name for event in sink.events]


async def test_thread_backend_propagates_opentelemetry_context() -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    sink = OpenTelemetryObservabilitySink(
        TracerProvider().get_tracer("parsefabric-thread-test")
    )
    async with ThreadExecutionBackend(max_workers=1, sink=sink) as backend:
        is_recording = await backend.run(
            lambda: trace.get_current_span().get_span_context().is_valid
        )
    assert is_recording
