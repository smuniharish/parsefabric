import json
from datetime import UTC, datetime
from typing import cast

import pytest

from parsefabric import Evidence, ParseContext, ParsedEvent, ParserCapabilities
from parsefabric.aggregation import Aggregate, CountAggregate, EventAggregator
from parsefabric.errors import CapabilityError
from parsefabric.models import JSONValue, ParseResult
from parsefabric.serialization import dumps_result, loads_result


def test_evidence_rejects_invalid_span() -> None:
    with pytest.raises(ValueError, match="end_offset"):
        Evidence(start_offset=10, end_offset=9)
    with pytest.raises(ValueError, match="identifiers"):
        Evidence(parser_name=cast(str, 1))


def test_context_rejects_non_string_identifiers() -> None:
    with pytest.raises(ValueError, match="identifiers"):
        ParseContext(source_id=cast(str, 1))


def test_capabilities_reject_unsafe_partitioning() -> None:
    with pytest.raises(ValueError, match="partitionable"):
        ParserCapabilities(stateful=True, partitionable=True)
    with pytest.raises(CapabilityError):
        ParserCapabilities(stateful=True).require_partitionable()


def test_context_and_result_serialization_round_trip() -> None:
    result = ParseResult(
        events=(
            ParsedEvent(
                "failure",
                {"count": 2},
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                evidence=Evidence(source_id="input", line_number=4),
            ),
        ),
        parser_name="demo",
        parser_version="1",
        correlation_id="c-1",
    )
    recovered = loads_result(dumps_result(result))
    assert recovered == result
    assert ParseContext(source_id="input").source_id == "input"


def test_serialization_rejects_future_versions_and_non_json_attributes() -> None:
    from parsefabric.errors import SerializationError

    future = ParseResult().to_dict() | {"schema_version": "2"}
    with pytest.raises(SerializationError, match="schema version"):
        loads_result(json.dumps(future))
    with pytest.raises(ValueError, match="JSON-compatible"):
        ParsedEvent("invalid", {"value": cast(JSONValue, object())})


def test_event_attributes_are_owned_by_the_event() -> None:
    attributes: dict[str, JSONValue] = {"items": [1]}
    event = ParsedEvent("x", attributes)
    nested = attributes["items"]
    assert isinstance(nested, list)
    nested.append(2)
    exported = event.to_dict()["attributes"]
    assert isinstance(exported, dict)
    exported["items"] = []
    assert event.attributes == {"items": [1]}


async def test_aggregate_is_associative_and_merges_time_bounds() -> None:
    aggregator = EventAggregator(group_by=("code",))
    events = [
        ParsedEvent("error", {"code": "x"}, datetime(2026, 1, day, tzinfo=UTC))
        for day in (1, 2, 3)
    ]
    whole = await aggregator.aggregate(events)
    left = await aggregator.aggregate(events[:1])
    right = await aggregator.aggregate(events[1:])
    merged = await aggregator.merge((*left, *right))
    assert merged == whole
    assert merged[0].count == 3


async def test_event_accumulator_adds_events_and_partial_summaries_incrementally() -> (
    None
):
    aggregator = EventAggregator(group_by=("code",))
    accumulator = aggregator.accumulator()
    accumulator.add([ParsedEvent("error", {"code": "x"})])
    accumulator.merge(await aggregator.aggregate([ParsedEvent("error", {"code": "x"})]))
    assert accumulator.result() == await aggregator.aggregate(
        [
            ParsedEvent("error", {"code": "x"}),
            ParsedEvent("error", {"code": "x"}),
        ]
    )


def test_aggregate_rejects_mismatched_merge() -> None:
    one = CountAggregate("one", 1, None, None, {})
    two = CountAggregate("two", 1, None, None, {})
    with pytest.raises(ValueError, match="different"):
        one.merge(two)


def test_aggregate_merge_distinguishes_json_booleans_from_numbers() -> None:
    boolean = CountAggregate("event", 1, None, None, {"value": True})
    number = CountAggregate("event", 1, None, None, {"value": 1})

    with pytest.raises(ValueError, match="different groups"):
        boolean.merge(number)


def test_aggregate_rejects_invalid_runtime_values() -> None:
    with pytest.raises(ValueError, match="count"):
        Aggregate("error", True, None, None)
    with pytest.raises(ValueError, match="timestamps"):
        Aggregate("error", 1, cast(datetime, 1), None)


async def test_statistical_aggregates_are_typed_and_lossy() -> None:
    (aggregate,) = await EventAggregator(group_by=("code",)).aggregate(
        [
            ParsedEvent(
                "error", {"code": "x"}, timestamp=datetime(2026, 2, 1, tzinfo=UTC)
            )
        ]
    )
    assert isinstance(aggregate, CountAggregate)
    assert aggregate.key_attributes == {"code": "x"}
    assert not EventAggregator().lossless
    assert not EventAggregator().requires_source
    with pytest.raises(CapabilityError, match="lossy"):
        await EventAggregator().materialize((aggregate,))
