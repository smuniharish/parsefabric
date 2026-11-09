"""Tests for a custom parser, to copy next to it.

Change the import to your parser and replace ``SAMPLE`` with a realistic
input that produces at least one event. ``check_parser`` runs the contract
the engine relies on: a JSON round trip, repeatable results for a
deterministic parser, and aggregates that rebuild the events exactly.

The tests run with plain pytest; no async plugin is needed.
"""

from __future__ import annotations

import asyncio

from parser_template import KeyValueParser

from parsefabric import ParseContext, ParseEngine
from parsefabric.partitioning import LinePartitioner
from parsefabric.testing import check_parser, check_partitioner

SAMPLE = (
    'event=checkout level=info user=42 message="cart opened"\n'
    "event=payment level=error user=42 gateway=stripe\n"
    "this line is not a record\n"
    "event=payment level=error user=43 gateway=stripe\n"
)
CONTEXT = ParseContext(source_id="sample.kv")


def test_parser_honors_the_contract() -> None:
    result = asyncio.run(check_parser(KeyValueParser(), SAMPLE, CONTEXT))

    assert [event.event_type for event in result.events] == ["checkout", "payment", "payment"]
    assert [event.evidence.line_number for event in result.events] == [1, 2, 4]
    assert result.events[1].severity == "ERROR"
    assert result.events[0].attributes["message"] == "cart opened"


def test_unparsable_lines_are_reported() -> None:
    result = asyncio.run(ParseEngine().parse(KeyValueParser(), SAMPLE, CONTEXT))

    assert [issue.message for issue in result.errors] == ["line 3 is not a key=value record"]


def test_partitions_parse_like_the_whole_document() -> None:
    async def partitioned() -> list[tuple[str, int]]:
        parser = KeyValueParser()
        partitions = await check_partitioner(
            LinePartitioner(max_lines=2), SAMPLE.splitlines(), capabilities=parser.capabilities
        )
        found = []
        for partition in partitions:
            context = ParseContext(source_id="sample.kv", source_offset=partition.start_offset)
            result = await parser.parse(partition.content, context)
            found.extend(
                (event.event_type, partition.start_line + (event.evidence.line_number or 0) - 1)
                for event in result.events
            )
        return found

    assert asyncio.run(partitioned()) == [("checkout", 1), ("payment", 2), ("payment", 4)]
