"""Helpers for asynchronous iterators in tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterable


async def collect[T](items: AsyncIterable[T]) -> tuple[T, ...]:
    """Drain an asynchronous iterable into a tuple."""
    return tuple([item async for item in items])
