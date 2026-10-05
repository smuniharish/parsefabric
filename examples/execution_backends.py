"""Run the same parser on the event loop, in threads, in processes and a custom backend.

Run: python examples/execution_backends.py
"""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, overload

from parsefabric.builtins import ApplicationLogParser
from parsefabric.execution import (
    AsyncExecutionBackend,
    ExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)

LINES = [f"order {number} payment timed out" for number in range(1, 9)]


class AuditedBackend(ExecutionBackend):
    """Count submissions, then delegate to another backend."""

    def __init__(self, delegate: ExecutionBackend) -> None:
        super().__init__()
        self._delegate = delegate
        self.submitted = 0

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
        self, function: Callable[..., R], /, *args: object, **kwargs: object
    ) -> R: ...

    async def run(
        self, function: Callable[..., Any], /, *args: object, **kwargs: object
    ) -> Any:
        self.submitted += 1
        return await self._delegate.run(function, *args, **kwargs)

    async def shutdown(self) -> None:
        await self._delegate.shutdown()


async def main() -> None:
    parser = ApplicationLogParser()
    results = {}
    for backend in (
        AsyncExecutionBackend(),
        ThreadExecutionBackend(max_workers=2),
        ProcessExecutionBackend(max_workers=2),
    ):
        async with backend:
            results[type(backend).__name__] = await backend.run(parser.parse, LINES[0])
    for name, result in results.items():
        print(f"{name:<24} {[event.event_type for event in result.events]}")
    first, *others = results.values()
    print("identical results:", all(result == first for result in others))

    async with AuditedBackend(ProcessExecutionBackend(max_workers=2)) as audited:
        events = [
            len(result.events)
            async for result in audited.map(parser.parse, LINES, max_in_flight=4)
        ]
    print(f"mapped {len(events)} inputs, {sum(events)} events")
    print(f"audited submissions: {audited.submitted}")


if __name__ == "__main__":
    asyncio.run(main())
