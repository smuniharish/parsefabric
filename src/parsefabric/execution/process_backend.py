"""Process pool execution backend."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from typing import TYPE_CHECKING

from parsefabric.execution._executor import ExecutorBackend, validated_workers

if TYPE_CHECKING:
    from parsefabric.observability import ObservabilitySink


class ProcessExecutionBackend(ExecutorBackend):
    """Run CPU-heavy work in an owned, spawn-based process pool.

    The callable, its arguments and its result must be picklable. Workers are
    started with the ``spawn`` method on every platform, so they never
    inherit the parent's threads or locks. An awaitable result is run to
    completion in the worker. A process pool is not a security sandbox.

    Args:
        max_workers: Number of processes; defaults to the standard library's
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
            ProcessPoolExecutor(
                max_workers=validated_workers(max_workers),
                mp_context=get_context("spawn"),
            ),
            sink,
            shutdown_timeout=shutdown_timeout,
        )
