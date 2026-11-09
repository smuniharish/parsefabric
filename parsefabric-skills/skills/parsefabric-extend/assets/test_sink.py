"""Tests for a custom observability sink, to copy next to it.

Change the import to your sink. ``check_observability_sink`` sends events
with and without attributes, then flushes and closes the sink; the other
tests check that a real parse reaches the sink and nothing is lost on close.

The tests run with plain pytest; no async plugin is needed.
"""

from __future__ import annotations

import asyncio

from sink_template import BatchingSink

from parsefabric import ParseEngine
from parsefabric.builtins import ApplicationLogParser
from parsefabric.testing import check_observability_sink


def test_sink_honors_the_contract() -> None:
    sink = BatchingSink(batch_size=1)
    asyncio.run(check_observability_sink(sink))

    assert [record["name"] for batch in sink.sent for record in batch] == [
        "ParseStarted",
        "ParseCompleted",
    ]


def test_close_delivers_buffered_events() -> None:
    async def parse() -> BatchingSink:
        sink = BatchingSink(batch_size=1000)
        await ParseEngine(sink).parse(ApplicationLogParser(), "db timeout\n")
        assert not sink.sent
        await sink.close()
        return sink

    sink = asyncio.run(parse())
    names = [record["name"] for batch in sink.sent for record in batch]
    assert names[0] == "ParserSelected"
    assert "ParseCompleted" in names
    assert all(record["parser"] == "application-log" for record in sink.sent[0])
