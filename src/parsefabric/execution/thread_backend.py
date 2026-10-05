"""Thread pool execution backend."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from parsefabric.execution._executor import _ExecutorBackend, validated_workers
from parsefabric.observability import ObservabilitySink


class ThreadExecutionBackend(_ExecutorBackend):
    """Run blocking work in an owned thread pool.

    Context variables of the caller are visible in the worker thread. An
    awaitable result is run to completion on a new event loop in the worker.
    Cancelling a call stops waiting for it but cannot interrupt a running
    thread.

    Args:
        max_workers: Number of threads; defaults to the standard library's
            choice.
        sink: Destination for ``Execution*`` lifecycle events.

    Raises:
        ValueError: If ``max_workers`` is not a positive integer or ``None``.
    """

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        sink: ObservabilitySink | None = None,
    ) -> None:
        super().__init__(
            ThreadPoolExecutor(max_workers=validated_workers(max_workers)), sink
        )
