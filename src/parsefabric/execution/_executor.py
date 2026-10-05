"""Shared implementation of the thread and process pool backends."""

from __future__ import annotations

import asyncio
import contextvars
import inspect
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import partial
from typing import Any, overload, override

from parsefabric.execution.base import ExecutionBackend
from parsefabric.observability import LifecycleEvent, ObservabilitySink


async def _await(awaitable: Awaitable[Any]) -> Any:
    return await awaitable


def _call_in_worker(
    function: Callable[..., Any], args: tuple[object, ...], kwargs: dict[str, object]
) -> Any:
    """Call ``function`` in a worker and drive an awaitable result to completion."""
    result = function(*args, **kwargs)
    if inspect.isawaitable(result):
        return asyncio.run(_await(result))
    return result


def validated_workers(max_workers: object) -> int | None:
    """Return ``max_workers`` if it is ``None`` or a positive integer."""
    if max_workers is not None and (type(max_workers) is not int or max_workers < 1):
        raise ValueError("max_workers must be a positive integer or None")
    return max_workers


class _ExecutorBackend(ExecutionBackend):
    def __init__(
        self,
        executor: Executor,
        sink: ObservabilitySink | None = None,
    ) -> None:
        super().__init__(sink)
        self._executor = executor
        self._closed = False

    @overload
    async def run[R](
        self,
        function: Callable[..., Coroutine[Any, Any, R] | Awaitable[R]],
        /,
        *args: object,
        **kwargs: object,
    ) -> R: ...

    @overload
    async def run[R](
        self,
        function: Callable[..., R],
        /,
        *args: object,
        **kwargs: object,
    ) -> R: ...

    @override
    async def run(
        self, function: Callable[..., Any], /, *args: object, **kwargs: object
    ) -> Any:
        if self._closed:
            raise RuntimeError("execution backend is shut down")
        self._sink.emit(LifecycleEvent("ExecutionSubmitted"))
        call = partial(_call_in_worker, function, args, kwargs)
        loop = asyncio.get_running_loop()
        self._sink.emit(LifecycleEvent("ExecutionStarted"))
        try:
            if isinstance(self._executor, ThreadPoolExecutor):
                context = contextvars.copy_context()
                result = await loop.run_in_executor(self._executor, context.run, call)
            else:
                result = await loop.run_in_executor(self._executor, call)
        except asyncio.CancelledError:
            self._sink.emit(LifecycleEvent("ExecutionCancelled"))
            raise
        except Exception as error:
            self._sink.emit(
                LifecycleEvent(
                    "ExecutionFailed",
                    attributes={"error_type": type(error).__name__},
                )
            )
            raise
        self._sink.emit(LifecycleEvent("ExecutionCompleted"))
        return result

    @override
    async def shutdown(self) -> None:
        if not self._closed:
            self._closed = True
            await asyncio.to_thread(
                self._executor.shutdown, wait=True, cancel_futures=True
            )
