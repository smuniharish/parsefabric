"""Thread pool execution backend."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from parsefabric.execution._executor import ExecutorBackend, validated_workers

if TYPE_CHECKING:
    from parsefabric.observability import ObservabilitySink


class ThreadExecutionBackend(ExecutorBackend):
    """Run blocking work in an owned thread pool.

    Context variables of the caller are visible in the worker thread. An
    awaitable result is run on an event loop that each worker thread creates
    once and reuses.
    Cancelling a call stops waiting for it but cannot interrupt a running
    thread.

    Args:
        max_workers: Number of threads; defaults to the standard library's
            choice.
        sink: Destination for ``Execution*`` lifecycle events.
        shutdown_timeout: Seconds `shutdown` waits for running work;
            ``None`` waits until it finishes.

    Raises:
        ValueError: If ``max_workers`` is not a positive integer or ``None``,
            or ``shutdown_timeout`` is not a positive finite number or ``None``.
    """

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        sink: ObservabilitySink | None = None,
        shutdown_timeout: float | None = None,
    ) -> None:
        super().__init__(
            ThreadPoolExecutor(max_workers=validated_workers(max_workers)),
            sink,
            shutdown_timeout=shutdown_timeout,
        )
