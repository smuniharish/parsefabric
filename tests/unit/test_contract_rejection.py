"""Invalid contracts fail explicitly before scheduling or accepting evidence."""

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from parsefabric import Evidence, ParsedEvent, ParserCapabilities
from parsefabric.aggregation import (
    Aggregate,
    CountAggregate,
    EventAggregator,
    EvidenceAggregator,
    EvidenceEntry,
    EvidenceGroup,
    RoutingAggregator,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import IntegrityError, ParseIssue, SerializationError
from parsefabric.execution import AsyncExecutionBackend
from parsefabric.models import ParseResult, PatternStatistic
from parsefabric.parser import DeterministicParser
from parsefabric.serialization import loads_result


@pytest.mark.parametrize("matches", [True, False, 1.5, "1", None, -1])
def test_statistics_reject_noninteger_counts(matches: Any) -> None:
    with pytest.raises(ValueError):
        PatternStatistic("record", matches)


@pytest.mark.parametrize("name", [None, 1, True, "", []])
def test_statistics_reject_nonstring_names(name: Any) -> None:
    with pytest.raises(ValueError):
        PatternStatistic(name, 1)


@pytest.mark.parametrize("budget", [True, False, 1.5, "1", None, 0, -1])
async def test_scheduling_budgets_reject_invalid_values(budget: Any) -> None:
    parser = DeterministicParser([], name="empty")

    async def map_items() -> None:
        async for _ in AsyncExecutionBackend().map(
            lambda item: item, [1, 2], max_in_flight=budget
        ):
            pytest.fail("invalid scheduling budget submitted work")

    async def parse_items() -> None:
        async for _ in ParseEngine().parse_async_iter(
            parser, ["x"], max_concurrency=budget
        ):
            pytest.fail("invalid scheduling budget submitted parsing")

    with pytest.raises(ValueError):
        await map_items()
    with pytest.raises(ValueError):
        await parse_items()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message", object()),
        ("message", float("nan")),
        ("positions", [1]),
        ("positions", (True,)),
        ("positions", (0,)),
        ("positions", (2, 1)),
        ("occurrences", True),
        ("events", (object(),)),
        ("sequence", (-1,)),
    ],
)
def test_entry_rejects_invalid_fields(field: str, value: Any) -> None:
    values = {"message": "x", "occurrences": 1, "positions": (1,)}
    values[field] = value
    if value == (2, 1):
        values["occurrences"] = 2
    with pytest.raises(ValueError):
        EvidenceEntry(**values)


@pytest.mark.parametrize("field", ["pattern", "severity", "evidence"])
def test_group_rejects_invalid_fields(field: str) -> None:
    values: dict[str, Any] = {
        "pattern": None,
        "severity": None,
        "evidence": (EvidenceEntry("x", 1, (1,)),),
    }
    values[field] = 1
    with pytest.raises(ValueError):
        EvidenceGroup(**values)


@pytest.mark.parametrize(
    "field", ["source_id", "parser_name", "parser_version", "groups"]
)
async def test_document_rejects_invalid_fields(field: str) -> None:
    (document,) = await EvidenceAggregator().aggregate([ParsedEvent("x")])
    changes: dict[str, Any] = {field: 1}
    with pytest.raises(ValueError):
        replace(document, **changes)


async def test_document_rejects_partial_retention() -> None:
    (document,) = await EvidenceAggregator().aggregate([ParsedEvent("x")])
    with pytest.raises(ValueError, match="every entry"):
        replace(
            document,
            count=2,
            groups=(
                document.groups[0],
                EvidenceGroup(None, None, (EvidenceEntry("x", 1, (None,)),)),
            ),
        )


async def test_aggregator_rejects_invalid_events_messages_and_versions() -> None:
    with pytest.raises(TypeError, match="ParsedEvent"):
        await EvidenceAggregator().aggregate([object()])  # type: ignore[list-item]
    invalid = EvidenceAggregator(message=lambda _: object())  # type: ignore[arg-type,return-value]
    with pytest.raises(TypeError, match="JSON-compatible"):
        await invalid.aggregate([ParsedEvent("x")])
    first = ParsedEvent("x", evidence=Evidence(parser_name="p", parser_version="1"))
    changed = replace(first, evidence=replace(first.evidence, parser_version="2"))
    with pytest.raises(ValueError, match="different versions"):
        await EvidenceAggregator().aggregate([first, changed])
    unnamed = replace(first, evidence=replace(first.evidence, parser_name=None))
    changed_unnamed = replace(
        changed, evidence=replace(changed.evidence, parser_name=None)
    )
    with pytest.raises(ValueError, match="share a version"):
        await EvidenceAggregator().aggregate([unnamed, changed_unnamed])


async def test_materialize_rejects_wrong_type_source_sequence_and_candidates() -> None:
    aggregator = EvidenceAggregator()
    (document,) = await aggregator.aggregate([ParsedEvent("x")])
    with pytest.raises(TypeError, match="EvidenceAggregate"):
        await aggregator.materialize([Aggregate("x", 1, None, None)])
    with pytest.raises(IntegrityError, match="one source"):
        await aggregator.materialize(
            [document, replace(document, event_type="y", source_id="other")]
        )
    group = document.groups[0]
    bad_sequence = replace(group.evidence[0], sequence=(1,))
    forged = replace(document, groups=(replace(group, evidence=(bad_sequence,)),))
    with pytest.raises(IntegrityError, match="positions"):
        await aggregator.materialize([forged])
    with pytest.raises(IntegrityError, match="cannot be aggregated"):
        await aggregator.materialize([document], [object()])  # type: ignore[list-item]
    compact = await EvidenceAggregator(reproducible=True).aggregate([ParsedEvent("x")])
    with pytest.raises(IntegrityError, match="re-parsing"):
        await EvidenceAggregator(reproducible=True).materialize(compact)


async def _partials(item: Aggregate) -> AsyncIterator[Aggregate]:
    yield item


async def test_async_evidence_merge_and_invalid_partial() -> None:
    aggregator = EvidenceAggregator()
    (document,) = await aggregator.aggregate([ParsedEvent("x")])
    assert await aggregator.merge(_partials(document)) == (document,)
    with pytest.raises(TypeError, match="EvidenceAggregate"):
        await aggregator.merge(_partials(Aggregate("x", 1, None, None)))


@pytest.mark.parametrize(
    "change",
    [
        {"warnings": [1]},
        {"warnings": None},
        {"errors": "bad"},
        {"errors": [None]},
        {"errors": [ParseIssue("x", "bad").to_dict() | {"error_type": 1}]},
        {"errors": [ParseIssue("x", "bad").to_dict() | {"source_id": 1}]},
        {"errors": [ParseIssue("x", "bad").to_dict() | {"input_index": True}]},
        {"errors": [ParseIssue("x", "bad").to_dict() | {"input_index": -1}]},
        {"errors": [{"error_type": "x", "message": "bad"}]},
        {"parser_name": 1},
        {"correlation_id": False},
        {"events": None},
        {"pattern_statistics": [{"pattern_name": "x", "matches": True}]},
        {"pattern_statistics": [{"pattern_name": "x", "matches": 1}] * 2},
        {"llm_result": ""},
        {"schema_version": "2"},
        {"extra": None},
    ],
)
def test_result_decoder_rejects_invalid_contract_fields(change: dict[str, Any]) -> None:
    document = ParseResult().to_dict() | change
    with pytest.raises(SerializationError):
        loads_result(json.dumps(document))


@pytest.mark.parametrize("field", list(ParseResult().to_dict()))
def test_result_decoder_requires_every_field(field: str) -> None:
    document = ParseResult().to_dict()
    del document[field]
    with pytest.raises(SerializationError, match="missing"):
        loads_result(json.dumps(document))


@pytest.mark.parametrize("group_by", [("",), ("x", "x")])
def test_invalid_statistical_group_names(group_by: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        EventAggregator(group_by=group_by)


async def test_statistical_async_paths_and_partial_type_rejection() -> None:
    async def events() -> AsyncIterator[ParsedEvent]:
        yield ParsedEvent("x")

    aggregator = EventAggregator()
    (aggregate,) = await aggregator.aggregate(events())
    assert await aggregator.merge(_partials(aggregate)) == (aggregate,)
    with pytest.raises(TypeError):
        await aggregator.merge(_partials(Aggregate("x", 1, None, None)))


def test_count_and_base_aggregate_validation() -> None:
    with pytest.raises(ValueError):
        Aggregate(
            "x", 1, datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)
        )
    with pytest.raises(ValueError):
        CountAggregate.from_dict([])
    with pytest.raises(ValueError, match="missing key_attributes"):
        CountAggregate.from_dict({"event_type": "x", "count": 1})
    with pytest.raises(ValueError, match="unknown fields extra"):
        CountAggregate.from_dict(
            CountAggregate("x", 1, None, None, {}).to_dict() | {"extra": 1}
        )
    with pytest.raises(ValueError, match="ISO 8601"):
        Aggregate.from_dict({"event_type": "x", "count": 1, "first_seen": None})
    with pytest.raises(ValueError):
        CountAggregate("x", 1, None, None, {"value": float("inf")})
    with pytest.raises(TypeError):
        CountAggregate("x", 1, None, None, {}).merge(Aggregate("x", 1, None, None))  # type: ignore[arg-type]
    assert Aggregate.from_dict(Aggregate("x", 1, None, None).to_dict()) == Aggregate(
        "x", 1, None, None
    )


async def test_routed_async_materialization_merge_and_properties() -> None:
    default, child = EvidenceAggregator(), EvidenceAggregator(reproducible=True)
    routing = RoutingAggregator(default, {"child": child})
    assert routing.default is default
    assert routing.routes == {"child": child}
    assert routing.lossless
    assert routing.requires_source
    event = ParsedEvent("x", evidence=Evidence(parser_name="child", line_number=1))

    async def events() -> AsyncIterator[ParsedEvent]:
        yield event

    aggregates = await routing.aggregate(events())
    with pytest.raises(IntegrityError, match="fresh re-parse"):
        await routing.materialize(aggregates)
    assert await routing.materialize(aggregates, [event]) == (event,)
    assert await routing.merge(_partials(aggregates[0])) == aggregates
    with pytest.raises(TypeError):
        RoutingAggregator(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RoutingAggregator(default, {"bad": object()})  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        await routing.aggregate([object()])  # type: ignore[list-item]


async def test_routed_retained_materialization_requires_unambiguous_positions() -> None:
    routing = RoutingAggregator(EvidenceAggregator(), {"child": EvidenceAggregator()})
    events = [
        ParsedEvent("x", evidence=Evidence(parser_name="child", line_number=1)),
        ParsedEvent("y", evidence=Evidence(line_number=2)),
    ]
    aggregates = await routing.aggregate(events)
    assert await routing.materialize(aggregates) == tuple(events)
    assert await routing.merge(aggregates) == aggregates
    assert await RoutingAggregator(EvidenceAggregator()).materialize(
        await EvidenceAggregator().aggregate(events)
    ) == tuple(events)
    unpositioned = [
        replace(event, evidence=replace(event.evidence, line_number=None))
        for event in events
    ]
    with pytest.raises(IntegrityError, match="line numbers"):
        await routing.materialize(await routing.aggregate(unpositioned))


def test_deterministic_rejects_invalid_declarations() -> None:
    with pytest.raises(ValueError, match="name"):
        DeterministicParser([], name="")
    with pytest.raises(ValueError, match="deterministic"):
        DeterministicParser([], name="x", capabilities=ParserCapabilities())
