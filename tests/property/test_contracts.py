"""Generated inputs must preserve complete results, provenance, and evidence.

Example counts, deadlines and determinism come from the Hypothesis profile
selected in ``tests/conftest.py``.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from parsefabric import Evidence, ParseContext, ParsedEvent
from parsefabric.aggregation import EventAggregator, EvidenceAggregator
from parsefabric.builtins import JSONParser
from parsefabric.engine import ParseEngine
from parsefabric.models import JSONValue
from parsefabric.parser import DeterministicParser
from parsefabric.partitioning import LinePartitioner
from parsefabric.patterns import RegexPattern
from parsefabric.serialization import dumps_result, loads_result

BOUNDARIES = (
    "\n",
    "\r",
    "\r\n",
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)
UNICODE = st.characters(exclude_categories=("Cs",))
RECORDS = st.text(
    st.characters(exclude_categories=("Cs",), exclude_characters="".join(BOUNDARIES)),
    max_size=48,
)
JSON_VALUES = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**128), max_value=2**128)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(UNICODE, max_size=24),
    lambda child: (
        st.lists(child, max_size=5)
        | st.dictionaries(st.text(UNICODE, max_size=12), child, max_size=5)
    ),
    max_leaves=24,
)


async def _stream(events: tuple[ParsedEvent, ...]) -> AsyncIterator[ParsedEvent]:
    for event in events:
        yield event


def _parser() -> DeterministicParser:
    return DeterministicParser(
        [RegexPattern("record", r"^(?P<message>.*)$")], name="generated-records"
    )


@given(source=st.text(UNICODE, max_size=500), offset=st.integers(0, 4096))
def test_generated_unicode_parse_bytes_spans_and_evidence_roundtrip(
    source: str, offset: int
) -> None:
    async def verify() -> None:
        parser, engine = _parser(), ParseEngine()
        context = ParseContext(source_id="generated", source_offset=offset)
        result = await engine.parse(parser, source, context)
        assert result == await engine.parse(parser, source.encode("utf-8"), context)
        assert loads_result(dumps_result(result)) == result
        cursor = offset
        assert len(result.events) == len(source.splitlines())
        for number, (event, raw) in enumerate(
            zip(result.events, source.splitlines(keepends=True), strict=True), start=1
        ):
            assert event.evidence.line_number == number
            assert event.evidence.start_offset == cursor
            cursor += len(raw.encode("utf-8"))
            assert event.evidence.end_offset == cursor
            assert event.attributes["message"] == raw.splitlines()[0]
        assert cursor == offset + len(source.encode("utf-8"))
        aggregates = await parser.aggregate(_stream(result.events))
        decoded = parser.deserialize(parser.serialize(aggregates))
        rebuilt = await engine.materialize(parser, source, decoded, context)
        assert dumps_result(replace(result, events=rebuilt)) == dumps_result(result)

    asyncio.run(verify())


@given(
    records=st.lists(RECORDS, max_size=30),
    separator=st.sampled_from(BOUNDARIES),
    max_lines=st.integers(1, 12),
    extra_bytes=st.integers(0, 64),
)
def test_generated_partition_limits_exact_events_and_normalized_reconstruction(
    records: list[str], separator: str, max_lines: int, extra_bytes: int
) -> None:
    async def verify() -> None:
        parser = _parser()
        max_bytes = (
            max((len(record.encode("utf-8")) + 1 for record in records), default=1)
            + extra_bytes
        )
        partitions = tuple(
            LinePartitioner(max_lines=max_lines, max_bytes=max_bytes).partition(
                [record + separator for record in records],
                source_id="partitioned",
                capabilities=parser.capabilities,
            )
        )
        source = "".join(partition.content for partition in partitions)
        assert source == "\n".join(records)
        expected = await parser.parse(source, ParseContext(source_id="partitioned"))
        observed: list[ParsedEvent] = []
        byte_offset = 0
        for partition in partitions:
            assert partition.start_offset == byte_offset
            assert len(partition.content.splitlines()) <= max_lines
            byte_offset += len(partition.content.encode("utf-8"))
            assert len(partition.content.encode("utf-8")) <= max_bytes
            result = await parser.parse(
                partition.content,
                ParseContext(
                    source_id="partitioned", source_offset=partition.start_offset
                ),
            )
            for event in result.events:
                assert event.evidence.line_number is not None
                observed.append(
                    event.with_evidence(
                        replace(
                            event.evidence,
                            line_number=partition.start_line
                            + event.evidence.line_number
                            - 1,
                        )
                    )
                )
        assert tuple(observed) == expected.events

    asyncio.run(verify())


@given(value=JSON_VALUES)
def test_generated_json_retained_and_reparsed_materialization(value: JSONValue) -> None:
    async def verify() -> None:
        parser, engine = JSONParser(), ParseEngine()
        source = json.dumps(value, ensure_ascii=False, allow_nan=False)
        result = await engine.parse(parser, source, ParseContext(source_id="json"))
        assert not result.errors
        assert len(result.events) == 1
        assert result.events[0].attributes["value"] == value
        assert dumps_result(loads_result(dumps_result(result))) == dumps_result(result)
        for reproducible in (False, True):
            aggregator = EvidenceAggregator(reproducible=reproducible)
            aggregates = await aggregator.aggregate(result.events)
            decoded = parser.deserialize(parser.serialize(aggregates))
            rebuilt = await aggregator.materialize(
                decoded, result.events if reproducible else None
            )
            assert dumps_result(replace(result, events=rebuilt)) == dumps_result(result)

    asyncio.run(verify())


@given(values=st.lists(JSON_VALUES, max_size=20), split=st.integers(0, 20))
def test_generated_statistical_merge_matches_whole_with_json_type_identity(
    values: list[JSONValue], split: int
) -> None:
    async def verify() -> None:
        aggregator = EventAggregator(group_by=("value",))
        events = tuple(
            ParsedEvent(
                "record", {"value": value}, evidence=Evidence(line_number=index)
            )
            for index, value in enumerate(values, start=1)
        )
        whole = await aggregator.aggregate(events)
        left = await aggregator.aggregate(events[:split])
        right = await aggregator.aggregate(events[split:])
        merged = await aggregator.merge((*left, *right))
        assert [item.to_dict() for item in merged] == [item.to_dict() for item in whole]
        assert sum(item.count for item in merged) == len(values)

    asyncio.run(verify())


@given(payload=st.binary(max_size=256))
def test_generated_arbitrary_bytes_fail_explicitly_or_preserve_json_result(
    payload: bytes,
) -> None:
    async def verify() -> None:
        parser = JSONParser()
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            try:
                await parser.parse(payload)
            except UnicodeDecodeError:
                return
            raise AssertionError("invalid UTF-8 did not fail explicitly") from None
        result = await parser.parse(payload, ParseContext(source_id="bytes"))
        assert len(result.events) == 1
        event = result.events[0]
        assert event.evidence.start_offset == 0
        assert event.evidence.end_offset == len(payload)
        if result.errors:
            assert event.event_type == "unparsed"
            assert event.attributes == {"text": text}
            assert result.errors[0].source_id == "bytes"
        else:
            assert event.event_type == "json_record"
            assert event.attributes["value"] == json.loads(text)
        assert dumps_result(loads_result(dumps_result(result))) == dumps_result(result)

    asyncio.run(verify())
