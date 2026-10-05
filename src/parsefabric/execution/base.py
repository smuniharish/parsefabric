"""Backend-neutral execution contract."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterable
from typing import Any, Self, overload

from parsefabric.observability import NullObservabilitySink, ObservabilitySink


class ExecutionBackend(ABC):
    """Where submitted work runs: the event loop, threads, processes or a cluster.

    Parsers do not depend on the backend; applications choose one to bound
    concurrency or isolate CPU-heavy work. Backends are asynchronous context
    managers that release their resources on exit.

    Args:
        sink: Destination for ``Execution*`` lifecycle events. Defaults to a
            sink that discards them.
    """

    def __init__(self, sink: ObservabilitySink | None = None) -> None:
        self._sink = sink or NullObservabilitySink()

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

    @abstractmethod
    async def run(
        self, function: Callable[..., Any], /, *args: object, **kwargs: object
    ) -> Any:
        """Run one callable and return its result, awaiting awaitable results.

        Args:
            function: Synchronous or asynchronous callable.
            *args: Positional arguments for ``function``.
            **kwargs: Keyword arguments for ``function``.

        Returns:
            The callable's result.

        Raises:
            Exception: Whatever the callable raises.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Release resources owned by this backend; idempotent."""

    @overload
    def map[Input, Output](
        self,
        function: Callable[[Input], Coroutine[Any, Any, Output] | Awaitable[Output]],
        items: Iterable[Input],
        *,
        max_in_flight: int = 1,
    ) -> AsyncIterator[Output]: ...

    @overload
    def map[Input, Output](
        self,
        function: Callable[[Input], Output],
        items: Iterable[Input],
        *,
        max_in_flight: int = 1,
    ) -> AsyncIterator[Output]: ...

    async def map[Input](
        self,
        function: Callable[[Input], Any],
        items: Iterable[Input],
        *,
        max_in_flight: int = 1,
    ) -> AsyncIterator[Any]:
        """Apply a callable to every item with a bound on outstanding work.

        At most ``max_in_flight`` calls are scheduled but not yet consumed.
        Results are yielded in completion order. The first failure is raised
        and outstanding calls are cancelled; work already running in a thread
        or process cannot be interrupted.

        Args:
            function: Callable applied to each item.
            items: Inputs, consumed lazily.
            max_in_flight: Maximum number of scheduled, unconsumed calls.

        Yields:
            One result per item.

        Raises:
            ValueError: If ``max_in_flight`` is not a positive integer.
        """
        if type(max_in_flight) is not int or max_in_flight < 1:
            raise ValueError("max_in_flight must be a positive integer")
        iterator = iter(items)
        pending: set[asyncio.Task[Any]] = set()
        exhausted = False
        try:
            while pending or not exhausted:
                while not exhausted and len(pending) < max_in_flight:
                    try:
                        item = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    pending.add(asyncio.create_task(self.run(function, item)))
                if pending:
                    completed, _ = await asyncio.wait(
                        pending,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in completed:
                        pending.remove(task)
                        yield task.result()
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.shutdown()
