import asyncio
import contextvars
import gc
import multiprocessing
import pickle
import threading
import time

import pytest

from parsefabric.builtins import ApplicationLogParser
from parsefabric.execution import (
    AsyncExecutionBackend,
    ExecutorBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.execution._executor import _process_loops, _WorkerLoops
from parsefabric.observability import (
    LifecycleEvent,
    ObservabilitySink,
    OpenTelemetryObservabilitySink,
)
from parsefabric.parser import Parser


class RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.events: list[LifecycleEvent] = []

    async def emit(self, event: LifecycleEvent) -> None:
        self.events.append(event)


def _square(value: int) -> int:
    return value * value


async def _parse_in_worker(parser: Parser, text: str) -> tuple[str, int]:
    result = await parser.parse(text)
    return result.events[0].event_type, id(asyncio.get_running_loop())


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

    def record_exception(loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
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
        event_type, _ = await backend.run(_parse_in_worker, ApplicationLogParser(), "timeout")
        assert event_type == "timeout"


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

    sink = OpenTelemetryObservabilitySink(TracerProvider().get_tracer("parsefabric-thread-test"))
    async with ThreadExecutionBackend(max_workers=1, sink=sink) as backend:
        is_recording = await backend.run(
            lambda: trace.get_current_span().get_span_context().is_valid
        )
    assert is_recording


_REQUEST: contextvars.ContextVar[str] = contextvars.ContextVar("request", default="none")


async def _loop_and_request() -> tuple[asyncio.AbstractEventLoop, str]:
    await asyncio.sleep(0)
    return asyncio.get_running_loop(), _REQUEST.get()


async def test_worker_threads_reuse_one_event_loop_and_close_it_on_shutdown() -> None:
    backend = ThreadExecutionBackend(max_workers=1)
    _REQUEST.set("first")
    first_loop, first_request = await backend.run(_loop_and_request)
    _REQUEST.set("second")
    second_loop, second_request = await backend.run(_loop_and_request)
    assert first_loop is second_loop
    assert (first_request, second_request) == ("first", "second")
    assert not first_loop.is_closed()
    await backend.shutdown()
    assert first_loop.is_closed()
    assert backend.closed


async def test_process_workers_reuse_their_event_loop() -> None:
    async with ProcessExecutionBackend(max_workers=1) as backend:
        first = await backend.run(_parse_in_worker, ApplicationLogParser(), "timeout")
        second = await backend.run(_parse_in_worker, ApplicationLogParser(), "timeout")
    assert first == second


def test_pickled_worker_loops_resolve_to_the_process_registry() -> None:
    restored = pickle.loads(pickle.dumps(_WorkerLoops()))
    assert restored is _process_loops() is _process_loops()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, "1"])
def test_shutdown_timeout_must_be_positive_and_finite(timeout: object) -> None:
    with pytest.raises(ValueError, match="shutdown_timeout"):
        # pyrefly: ignore[bad-argument-type]
        ThreadExecutionBackend(shutdown_timeout=timeout)
    with pytest.raises(ValueError, match="shutdown_timeout"):
        # pyrefly: ignore[bad-argument-type]
        ProcessExecutionBackend(shutdown_timeout=timeout)


async def test_shutdown_timeout_bounds_waiting_for_running_work() -> None:
    release = threading.Event()
    backend = ThreadExecutionBackend(max_workers=1, shutdown_timeout=0.05)
    running = asyncio.create_task(backend.run(release.wait, 5))
    await asyncio.sleep(0.05)
    with pytest.raises(TimeoutError, match=r"did not shut down within 0\.05 seconds"):
        await backend.shutdown()
    release.set()
    assert await running is True
    await backend.shutdown()


async def test_shutdown_during_submission_rejects_the_call() -> None:
    class ShutdownOnSubmit(RecordingSink):
        backend: ExecutorBackend

        async def emit(self, event: LifecycleEvent) -> None:
            await super().emit(event)
            if event.name == "ExecutionSubmitted":
                await self.backend.shutdown()

    sink = ShutdownOnSubmit()
    sink.backend = ThreadExecutionBackend(max_workers=1, sink=sink)
    with pytest.raises(RuntimeError, match="shut down"):
        await sink.backend.run(_square, 2)
    assert [event.name for event in sink.events] == ["ExecutionSubmitted", "ExecutionFailed"]
    with pytest.raises(RuntimeError, match="shut down"):
        await sink.backend.run(_square, 2)
