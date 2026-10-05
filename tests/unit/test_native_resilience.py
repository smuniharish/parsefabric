"""Cancellation, worker loss, and aborted streams retain explicit ownership."""

import asyncio
import gc
import os
import threading
from collections.abc import AsyncGenerator, AsyncIterator
from concurrent.futures.process import BrokenProcessPool

import pytest

from parsefabric import ParseContext, ParseResult
from parsefabric.engine import ParseEngine
from parsefabric.execution import (
    AsyncExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.parser import DeterministicParser


def _identity(value: int) -> int:
    return value


def _terminate_own_worker() -> None:
    os._exit(17)


async def _values() -> AsyncIterator[object]:
    yield "first"
    yield "second"
    yield "third"


class _FailingParser(DeterministicParser):
    def __init__(self) -> None:
        super().__init__([], name="fails")

    async def parse(
        self, source: object, context: ParseContext | None = None
    ) -> ParseResult:
        raise ValueError(f"expected failure: {source}")


@pytest.mark.parametrize("async_input", [False, True])
async def test_parallel_parse_observes_every_completed_failure_on_abort(
    async_input: bool,
) -> None:
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    unhandled: list[str] = []
    loop.set_exception_handler(
        lambda _, context: unhandled.append(str(context.get("message")))
    )
    try:
        source = _values() if async_input else ["first", "second", "third"]

        async def drain() -> None:
            async for _ in ParseEngine().parse_async_iter(
                _FailingParser(), source, max_concurrency=3
            ):
                pytest.fail("failed parser yielded success")

        with pytest.raises(ValueError, match="expected failure"):
            await drain()
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
        assert not unhandled
    finally:
        loop.set_exception_handler(previous)


async def test_map_early_close_cancels_awaiters_and_remains_reusable() -> None:
    entered = 0
    cancelled = 0
    blocked = asyncio.Event()
    all_entered = asyncio.Event()

    async def work(value: int) -> int:
        nonlocal entered, cancelled
        entered += 1
        if entered == 3:
            all_entered.set()
        if value == 0:
            await all_entered.wait()
            return value
        try:
            await blocked.wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise
        return value

    async with AsyncExecutionBackend() as backend:
        stream = backend.map(work, range(100), max_in_flight=3)
        assert isinstance(stream, AsyncGenerator)
        async with asyncio.timeout(5):
            assert await anext(stream) == 0
            await stream.aclose()
        assert entered == 3
        assert cancelled == 2
        assert await backend.run(_identity, 7) == 7


async def test_map_input_iteration_failure_cleans_up_scheduled_tasks() -> None:
    def failing_input():
        yield 1
        raise RuntimeError("input iterator failed")

    async with AsyncExecutionBackend() as backend:

        async def drain() -> None:
            async for _ in backend.map(_identity, failing_input(), max_in_flight=3):
                pytest.fail("iterator failure must abort")

        with pytest.raises(RuntimeError, match="iterator failed"):
            await drain()
        assert await backend.run(_identity, 9) == 9


async def test_thread_cancellation_does_not_claim_to_stop_running_work() -> None:
    started, release, completed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def work() -> int:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release worker")
        completed.set()
        return 11

    backend = ThreadExecutionBackend(max_workers=1)
    task = asyncio.create_task(backend.run(work))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not completed.is_set()
        release.set()
        assert await asyncio.to_thread(completed.wait, 5)
        assert await backend.run(_identity, 12) == 12
    finally:
        release.set()
        await backend.shutdown()
        await asyncio.gather(task, return_exceptions=True)
    await backend.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        await backend.run(_identity, 0)


async def test_real_process_loss_breaks_pool_explicitly_and_new_pool_recovers() -> None:
    backend = ProcessExecutionBackend(max_workers=1)
    try:
        async with asyncio.timeout(15):
            with pytest.raises(BrokenProcessPool):
                await backend.run(_terminate_own_worker)
            with pytest.raises(BrokenProcessPool):
                await backend.run(_identity, 1)
    finally:
        await backend.shutdown()
    async with ProcessExecutionBackend(max_workers=1) as replacement:
        async with asyncio.timeout(15):
            assert await replacement.run(_identity, 42) == 42


@pytest.mark.parametrize(
    "backend_type", [ThreadExecutionBackend, ProcessExecutionBackend]
)
async def test_executor_awaits_async_callables_and_reuses_pool_after_timeout(
    backend_type: type[ThreadExecutionBackend] | type[ProcessExecutionBackend],
) -> None:
    async with backend_type(max_workers=1) as backend:
        assert await backend.run(asyncio.sleep, 0, result=8) == 8
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await backend.run(asyncio.sleep, 0.05)
        assert await backend.run(_identity, 9) == 9
