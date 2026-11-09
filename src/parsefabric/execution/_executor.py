"""Execution on any `concurrent.futures.Executor`, shared by the pool backends."""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import inspect
import threading
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any, overload, override

from parsefabric._validation import validated_timeout
from parsefabric.execution.base import ExecutionBackend

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from parsefabric.observability import ObservabilitySink


async def _await(awaitable: Awaitable[Any]) -> Any:
    return await awaitable


class _WorkerLoops:
    """One reusable event loop per worker thread, closed when the backend shuts down.

    A pickled instance, such as one sent to a worker process, is restored as
    the worker process's own registry, which is closed when that process exits.
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._lock = threading.Lock()
        self._runners: list[asyncio.Runner] = []

    def run(self, awaitable: Awaitable[Any]) -> Any:
        runner: asyncio.Runner | None = getattr(self._local, "runner", None)
        if runner is None:
            runner = asyncio.Runner()
            self._local.runner = runner
            with self._lock:
                self._runners.append(runner)
        return runner.run(_await(awaitable), context=contextvars.copy_context())

    def close(self) -> None:
        with self._lock:
            runners, self._runners = self._runners, []
        for runner in runners:
            runner.close()

    def __reduce__(self) -> tuple[Callable[[], _WorkerLoops], tuple[()]]:
        return _process_loops, ()


_PROCESS_LOOPS: _WorkerLoops | None = None


def _process_loops() -> _WorkerLoops:
    global _PROCESS_LOOPS
    if _PROCESS_LOOPS is None:
        _PROCESS_LOOPS = _WorkerLoops()
        atexit.register(_PROCESS_LOOPS.close)
    return _PROCESS_LOOPS


def _call_in_worker(
    loops: _WorkerLoops,
    function: Callable[..., Any],
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> Any:
    """Call ``function`` in a worker and drive an awaitable result to completion."""
    result = function(*args, **kwargs)
    if inspect.isawaitable(result):
        return loops.run(result)
    return result


def validated_workers(max_workers: object) -> int | None:
    """Return ``max_workers`` if it is ``None`` or a positive integer."""
    if max_workers is not None and (type(max_workers) is not int or max_workers < 1):
        raise ValueError("max_workers must be a positive integer or None")
    return max_workers


class ExecutorBackend(ExecutionBackend):
    """Run work on a `concurrent.futures.Executor` that the backend owns.

    Use it to plug in any executor, such as a distributed or custom pool;
    `ThreadExecutionBackend` and `ProcessExecutionBackend` are built on it.
    An awaitable result is run to completion on an event loop that each
    worker thread creates once and reuses. With a `ThreadPoolExecutor` the
    caller's context variables are visible in the worker. `shutdown` cancels
    queued work, waits for running work and closes the worker event loops.

    Args:
        executor: Executor that runs the work; the backend takes ownership.
        sink: Destination for ``Execution*`` lifecycle events.
        shutdown_timeout: Seconds `shutdown` waits for running work;
            ``None`` waits until it finishes.

    Raises:
        TypeError: If ``executor`` is not a `concurrent.futures.Executor`.
        ValueError: If ``shutdown_timeout`` is not a positive finite number
            or ``None``.
    """

    def __init__(
        self,
        executor: Executor,
        sink: ObservabilitySink | None = None,
        *,
        shutdown_timeout: float | None = None,
    ) -> None:
        if not isinstance(executor, Executor):
            raise TypeError("executor must be a concurrent.futures.Executor")
        super().__init__(sink)
        self._executor = executor
        self._shutdown_timeout = validated_timeout("shutdown_timeout", shutdown_timeout)
        self._loops = _WorkerLoops()
        self._closed = False

    @property
    def closed(self) -> bool:
        """Whether `shutdown` has been called."""
        return self._closed

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
    async def run(self, function: Callable[..., Any], /, *args: object, **kwargs: object) -> Any:
        """Run ``function`` on the executor and return its result.

        Raises:
            RuntimeError: If the backend is shut down.
            Exception: Whatever the callable raises.
        """
        if self._closed:
            raise RuntimeError("execution backend is shut down")
        await self.emit("ExecutionSubmitted")
        call = partial(_call_in_worker, self._loops, function, args, kwargs)
        loop = asyncio.get_running_loop()
        try:
            # Checked again because shutdown may have started while emitting.
            if self._closed:
                raise RuntimeError("execution backend is shut down")
            if isinstance(self._executor, ThreadPoolExecutor):
                context = contextvars.copy_context()
                future = loop.run_in_executor(self._executor, context.run, call)
            else:
                future = loop.run_in_executor(self._executor, call)
        except Exception as error:
            await self.emit("ExecutionFailed", error_type=type(error).__name__)
            raise
        try:
            await self.emit("ExecutionStarted")
            result = await future
        except asyncio.CancelledError:
            future.cancel()
            await self.emit("ExecutionCancelled")
            raise
        except Exception as error:
            await self.emit("ExecutionFailed", error_type=type(error).__name__)
            raise
        await self.emit("ExecutionCompleted")
        return result

    def _shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._loops.close()

    @override
    async def shutdown(self) -> None:
        """Cancel queued work, wait for running work and close worker loops; idempotent.

        Raises:
            TimeoutError: If running work outlasts ``shutdown_timeout``. The
                executor keeps shutting down in the background.
        """
        if self._closed:
            return
        self._closed = True
        try:
            async with asyncio.timeout(self._shutdown_timeout):
                await asyncio.shield(asyncio.to_thread(self._shutdown))
        except TimeoutError:
            raise TimeoutError(
                f"execution backend did not shut down within {self._shutdown_timeout} seconds"
            ) from None
