"""Parse a stream incrementally, with bounded concurrency and tolerated failures.

Run: python examples/streaming.py
"""

import asyncio
from collections.abc import AsyncIterator

from parsefabric import ParseEngine
from parsefabric.builtins import ApplicationLogParser


async def requests() -> AsyncIterator[str | bytes]:
    """Simulate log lines arriving from a socket or queue."""
    for number in range(1, 7):
        await asyncio.sleep(0)
        yield f"request {number} timed out"
    yield b"\xff not UTF-8"


async def main() -> None:
    engine = ParseEngine()
    parser = ApplicationLogParser()

    print("in order:")
    async for result in engine.parse_iter(parser, requests(), continue_on_error=True):
        if result.errors:
            print(f"  failed: {result.errors[0].error_type}")
        else:
            print(f"  {result.events[0].attributes['message']}")

    events = 0
    failures = 0
    async for result in engine.parse_async_iter(
        parser, requests(), max_concurrency=3, continue_on_error=True
    ):
        events += len(result.events)
        failures += len(result.errors)
    print(f"concurrently: {events} events, {failures} recorded failure")


if __name__ == "__main__":
    asyncio.run(main())
