# Execution backends

An execution backend decides where work runs. ParseFabric ships backends for
the event loop, threads and processes, and `ExecutorBackend` adapts any
`concurrent.futures.Executor`. Write your own to run work on a task queue, a
cluster or a remote service.

Subclass `ExecutionBackend` and implement:

| Member | Contract |
| --- | --- |
| `async run(function, /, *args, **kwargs)` | Run one callable and return its result, awaiting it when the callable is asynchronous; raise whatever the callable raises |
| `async shutdown()` | Release the backend's resources; calling it again does nothing |

`map`, `emit` and the async context manager come from the base class: `map`
is built on `run`, so it bounds concurrency with `max_in_flight` and cancels
outstanding calls on the first failure for every backend. Pass `sink=` to
`super().__init__` and report `ExecutionSubmitted`, `ExecutionStarted`,
`ExecutionCompleted`, `ExecutionFailed` and `ExecutionCancelled` with
`await self.emit(name, **attributes)`, so sinks see the same lifecycle for
every backend.

A backend that runs blocking callables in `asyncio.to_thread`, at most
`limit` at a time across every caller:

```python
import asyncio
import inspect
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, overload

from parsefabric.builtins import ApplicationLogParser
from parsefabric.execution import ExecutionBackend
from parsefabric.observability import ObservabilitySink
from parsefabric.testing import check_execution_backend


class LimitedThreadBackend(ExecutionBackend):
    """Run coroutines on the loop and blocking calls in threads, `limit` at a time."""

    def __init__(self, limit: int, sink: ObservabilitySink | None = None) -> None:
        super().__init__(sink)
        self._slots = asyncio.Semaphore(limit)

    @overload
    async def run[R](
        self,
        function: Callable[..., Coroutine[Any, Any, R] | Awaitable[R]],
        /,
        *args: object,
        **kwargs: object,
    ) -> R: ...

    @overload
    async def run[R](self, function: Callable[..., R], /, *args: object, **kwargs: object) -> R: ...

    async def run(self, function: Callable[..., Any], /, *args: object, **kwargs: object) -> Any:
        async with self._slots:
            await self.emit("ExecutionStarted")
            try:
                if inspect.iscoroutinefunction(function):
                    result = await function(*args, **kwargs)
                else:
                    result = await asyncio.to_thread(function, *args, **kwargs)
            except Exception as error:
                await self.emit("ExecutionFailed", error_type=type(error).__name__)
                raise
            await self.emit("ExecutionCompleted")
            return result

    async def shutdown(self) -> None:
        return None


async def main() -> None:
    await check_execution_backend(LimitedThreadBackend(limit=2))
    parser = ApplicationLogParser()
    lines = [f"order {number} payment timed out" for number in range(6)]
    async with LimitedThreadBackend(limit=2) as backend:
        counts = [
            len(result.events) async for result in backend.map(parser.parse, lines, max_in_flight=4)
        ]
    print(f"{len(counts)} inputs, {sum(counts)} events")


asyncio.run(main())
```

```text
6 inputs, 6 events
```

The two `run` overloads tell type checkers that `run` returns what the
callable returns, awaited when it is a coroutine function.

`check_execution_backend(backend)` checks that the backend runs synchronous
and asynchronous callables, propagates their exceptions, maps every item
exactly once and shuts down twice without error. Process and cluster
backends must be able to import `parsefabric.testing` in their workers.

For Celery, Apache Spark and Apache Flink, see
[Distributed runtimes](../integrations/distributed-runtimes.md).
