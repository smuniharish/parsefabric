"""Asyncio execution backend."""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any, overload, override

from parsefabric.execution.base import ExecutionBackend

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine


class AsyncExecutionBackend(ExecutionBackend):
    """Run callables directly on the current event loop.

    Synchronous callables run inline and block the loop while they run, so
    use this backend for asynchronous parsers or light work. Awaitable
    results are awaited.

    Args:
        sink: Destination for ``Execution*`` lifecycle events.
    """

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
        await self.emit("ExecutionSubmitted")
        await self.emit("ExecutionStarted")
        try:
            result = function(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        except asyncio.CancelledError:
            await self.emit("ExecutionCancelled")
            raise
        except Exception as error:
            await self.emit("ExecutionFailed", error_type=type(error).__name__)
            raise
        await self.emit("ExecutionCompleted")
        return result

    @override
    async def shutdown(self) -> None:
        """Do nothing: the backend owns no resources."""
