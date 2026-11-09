"""Parsing tests to copy into your project's test suite.

Replace ``SAMPLE`` with a short, representative excerpt of your input, the
parser with the one your application uses, and ``EXPECTED`` with the events
the excerpt must produce. The tests check the evidence, that the stored form
rebuilds the original events exactly, and that a changed source is detected
instead of rebuilding wrong events.

The tests run with plain pytest; no async plugin is needed.
"""

from __future__ import annotations

import asyncio

import pytest

from parsefabric import IntegrityError, ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser

SAMPLE = (
    "2026-10-04T08:15:00Z INFO checkout started\n"
    "2026-10-04T08:15:02Z ERROR payment gateway timed out after 30s\n"
    "2026-10-04T08:15:03Z ERROR payment gateway timed out after 30s\n"
)
# (event type, line number) pairs the sample must produce.
EXPECTED = {("error", 2), ("error", 3), ("timeout", 2), ("timeout", 3)}
CONTEXT = ParseContext(source_id="sample.log")


def make_parser() -> ApplicationLogParser:
    return ApplicationLogParser()


def test_events_carry_evidence() -> None:
    result = asyncio.run(ParseEngine().parse(make_parser(), SAMPLE, CONTEXT))

    assert not result.errors
    assert {(event.event_type, event.evidence.line_number) for event in result.events} == EXPECTED
    source, lines = SAMPLE.encode(), SAMPLE.splitlines()
    for event in result.events:
        evidence = event.evidence
        assert evidence.source_id == CONTEXT.source_id
        assert evidence.line_number is not None
        assert evidence.start_offset is not None
        span = source[evidence.start_offset : evidence.end_offset].decode()
        assert span.rstrip("\n") in lines[evidence.line_number - 1]


def test_stored_aggregates_rebuild_the_events() -> None:
    async def round_trip() -> None:
        engine, parser = ParseEngine(), make_parser()
        result = await engine.parse(parser, SAMPLE, CONTEXT)
        stored = await engine.serialize(await engine.aggregate(parser, result.events))
        restored = await engine.deserialize(stored)
        assert await engine.materialize(parser, SAMPLE, restored, CONTEXT) == result.events

    asyncio.run(round_trip())


def test_a_changed_source_is_rejected() -> None:
    async def tampered() -> None:
        engine, parser = ParseEngine(), make_parser()
        result = await engine.parse(parser, SAMPLE, CONTEXT)
        aggregates = await engine.aggregate(parser, result.events)
        changed = SAMPLE.replace("30s", "31s")
        await engine.materialize(parser, changed, aggregates, CONTEXT)

    with pytest.raises(IntegrityError):
        asyncio.run(tampered())
