"""An observability sink to copy and adapt: batch lifecycle events to a service.

Replace ``send`` with your client call, such as a metrics API, a message
queue producer or an HTTP collector. The sink buffers events and sends them
in batches, so ``emit`` stays fast: callers await it inline.

Create the client in the event loop that uses it, and close the sink when
the application shuts down so buffered events are delivered.
"""

from __future__ import annotations

import asyncio
from typing import Any, override

from parsefabric.observability import LifecycleEvent, ObservabilitySink


class BatchingSink(ObservabilitySink):
    """Buffer lifecycle events and send them in batches of ``batch_size``."""

    def __init__(self, *, batch_size: int = 100) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._batch_size = batch_size
        self._buffer: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self.sent: list[list[dict[str, Any]]] = []
        self.closed = False

    async def send(self, batch: list[dict[str, Any]]) -> None:
        """Deliver one batch. Replace with your client call."""
        self.sent.append(batch)

    @override
    async def emit(self, event: LifecycleEvent) -> None:
        if self.closed:
            return
        record = {
            "name": event.name,
            "parser": event.parser_name,
            "partition": event.partition_id,
            "at": event.occurred_at.isoformat(),
            **dict(event.attributes),
        }
        async with self._lock:
            self._buffer.append(record)
            if len(self._buffer) < self._batch_size:
                return
            batch, self._buffer = self._buffer, []
        await self.send(batch)

    @override
    async def flush(self) -> None:
        async with self._lock:
            batch, self._buffer = self._buffer, []
        if batch:
            await self.send(batch)

    @override
    async def close(self) -> None:
        if not self.closed:
            await self.flush()
            self.closed = True
