"""Shared helpers for the benchmark scripts."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any


def run_sync[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from synchronous benchmark code.

    Uses a worker thread when the caller is already inside a running event
    loop (for example an asyncio execution backend running a sync callable).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()
