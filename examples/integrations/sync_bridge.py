"""Run a coroutine from the synchronous callbacks used by Celery, Spark and Flink."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any


def run_sync[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously inside an external runtime callback."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()
