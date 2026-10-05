"""Backends that run work on the event loop, in threads, in processes or elsewhere."""

from __future__ import annotations

from parsefabric.execution.async_backend import AsyncExecutionBackend
from parsefabric.execution.base import ExecutionBackend
from parsefabric.execution.process_backend import ProcessExecutionBackend
from parsefabric.execution.thread_backend import ThreadExecutionBackend

__all__ = [
    "AsyncExecutionBackend",
    "ExecutionBackend",
    "ProcessExecutionBackend",
    "ThreadExecutionBackend",
]
