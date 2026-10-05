"""Lossless grouped evidence aggregation and its canonical encoding."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from parsefabric import (
    Evidence,
    EvidenceAggregator,
    EvidenceEntry,
    EvidenceGroup,
    IntegrityError,
    ParseContext,
    ParsedEvent,
    ParseResult,
    SemanticParser,
)
from parsefabric.aggregation import (
    FORMAT,
    Aggregate,
    CountAggregate,
    EventAggregator,
    EvidenceAggregate,
)
from parsefabric.builtins import JSONParser, MixedContentParser, TimestampedLogParser
from parsefabric.engine import ParseEngine
from parsefabric.errors import CapabilityError, SerializationError
from tests.support.grouped import rows

LOG = """2026-10-01T08:00:00Z INFO service started
2026-10-01T08:00:01Z ERROR db timeout
2026-10-01T08:00:02Z ERROR db timeout
2026-10-01T08:00:03Z ERROR db timeout
2026-10-01T08:00:04Z WARN retrying
2026-10-01T08:00:05Z ERROR db timeout
"""


async def _run(
    parser: object, source: str, source_id: str = "ops.log"
) -> tuple[ParseResult, tuple[EvidenceAggregate, ...]]:
    engine = ParseEngine()
    result = await engine.parse(parser, source, ParseContext(source_id=source_id))  # type: ignore[arg-type]
    aggregates = await engine.aggregate(parser, result.events)  # type: ignore[arg-type]
    return result, aggregates


def _evidence(aggregate: Aggregate) -> EvidenceAggregate:
    assert isinstance(aggregate, EvidenceAggregate)
    return aggregate


def _event(line: int, message: str, start: int | None = None) -> ParsedEvent:
    return ParsedEvent(
        "log",
        {"message": message},
        severity="ERROR",
        evidence=Evidence(
            source_id="s",
            parser_name="p",
            line_number=line,
            start_offset=start,
            end_offset=None if start is None else start + 10,
        ),
    )


async def test_groups_consecutive_runs_by_severity() -> None:
    result, aggregates = await _run(TimestampedLogParser(), LOG)
    document = _evidence(aggregates[0])
    assert len(aggregates) == 1

    assert document.event_type == "log"
    assert (document.source_id, document.parser_name) == ("ops.log", "timestamped-log")
    assert document.count == 6
    assert not hasattr(document, "dependent")
    assert rows(document) == [
        ("INFO", "service started", "1", 1),
        ("ERROR", "db timeout", "2,3,4", 3),
        ("ERROR", "db timeout", "6", 1),
        ("WARN", "retrying", "5", 1),
    ]
    # A three-line run is one entry: the message is stored once.
    assert TimestampedLogParser().serialize(aggregates).count("db timeout") == 2
    assert not document.retains_events

    events = await ParseEngine().materialize(TimestampedLogParser(), LOG, aggregates)
    assert events == result.events


async def test_wire_format_has_no_dependency_mode() -> None:
    parser = TimestampedLogParser()
    _, aggregates = await _run(parser, LOG)
    (_data,) = json.loads(parser.serialize(aggregates))["aggregates"]
    (error,) = [group for group in aggregates[0].groups if group.severity == "ERROR"]
    assert isinstance(error, EvidenceGroup)
    assert error.pattern == "timestamped-log"
    assert [entry.positions for entry in error.evidence] == [(2, 3, 4), (6,)]


async def test_runs_break_on_gaps_between_filtered_events() -> None:
    aggregator = EvidenceAggregator(reproducible=True)
    by_offset = [_event(1, "x", 0), _event(2, "x", 11), _event(4, "x", 40)]
    (document,) = await aggregator.aggregate(by_offset)
    (group,) = document.groups
    assert [entry.positions for entry in group.evidence] == [(1, 2), (4,)]

    by_line = [_event(1, "x"), _event(2, "x"), _event(5, "x")]
    (document,) = await aggregator.aggregate(by_line)
    (group,) = document.groups
    assert [entry.occurrences for entry in group.evidence] == [2, 1]


async def test_materialize_detects_changed_source_with_same_structure() -> None:
    parser = TimestampedLogParser()
    _, aggregates = await _run(parser, LOG)
    changed = LOG.replace("retrying", "retryinG")

    with pytest.raises(IntegrityError):
        await ParseEngine().materialize(parser, changed, aggregates)


async def test_materialize_detects_wrong_context_and_tampering() -> None:
    parser = TimestampedLogParser()
    engine = ParseEngine()
    _, (document,) = await _run(parser, LOG)
    document = _evidence(document)
    first, *others = document.groups
    moved = dataclasses.replace(
        first,
        evidence=(dataclasses.replace(first.evidence[0], positions=(4,)),),
    )

    with pytest.raises(IntegrityError):
        await engine.materialize(
            parser, LOG, (document,), ParseContext(source_id="other.log")
        )
    with pytest.raises(IntegrityError):
        await engine.materialize(
            parser,
            LOG,
            (dataclasses.replace(document, events_sha256="0" * 64),),
        )
    with pytest.raises(IntegrityError, match="do not match"):
        await engine.materialize(
            parser, LOG, (dataclasses.replace(document, groups=(moved, *others)),)
        )
    with pytest.raises(ValueError, match="add up"):
        dataclasses.replace(document, count=document.count + 1)
    with pytest.raises(IntegrityError, match="duplicate"):
        await engine.materialize(parser, LOG, (document, document))


def _malformed(data: dict[str, Any], change: str) -> None:
    group = data["groups"][0]
    entry = group["evidence"][0]
    match change:
        case "event_type":
            data["event_type"] = ""
        case "groups":
            data["groups"] = "nope"
        case "group":
            data["groups"] = [[]]
        case "empty":
            group["evidence"] = []
        case "pattern":
            group["pattern"] = 1
        case "occurrences":
            entry["occurrences"] = 0
        case "positions":
            entry["positions"] = [1, 2]
        case "negative":
            entry["positions"] = [0]
        case "message":
            del entry["message"]
        case "count":
            data["count"] = 2
        case "sha":
            data["events_sha256"] = "X"
        case "time":
            data["first_seen"] = 5


@pytest.mark.parametrize(
    "change",
    [
        "event_type",
        "groups",
        "group",
        "empty",
        "pattern",
        "occurrences",
        "positions",
        "negative",
        "message",
        "count",
        "sha",
        "time",
    ],
)
async def test_decoding_rejects_malformed_aggregates(change: str) -> None:
    parser = TimestampedLogParser()
    _, aggregates = await _run(parser, "2026-10-01T08:00:00+00:00 INFO ready\n")
    document = json.loads(parser.serialize(aggregates))
    _malformed(document["aggregates"][0], change)
    with pytest.raises(SerializationError):
        parser.deserialize(json.dumps(document))


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"format": "other/1", "aggregates": []}',
        '{"format": "parsefabric.aggregates/1"}',
    ],
)
def test_decoding_rejects_unknown_envelopes(text: str) -> None:
    with pytest.raises(SerializationError):
        TimestampedLogParser().deserialize(text)


async def test_zero_events_materialize_to_nothing() -> None:
    parser = TimestampedLogParser()
    engine = ParseEngine()
    assert await EvidenceAggregator().aggregate([]) == ()
    assert await engine.materialize(parser, "", ()) == ()
    with pytest.raises(IntegrityError):
        await engine.materialize(parser, LOG, ())


class _Intent(SemanticParser):
    def __init__(self) -> None:
        super().__init__(name="intent")

    async def parse(
        self, source: object, context: ParseContext | None = None
    ) -> ParseResult:
        assert isinstance(source, str)
        events = tuple(
            self._with_parser_evidence(
                ParsedEvent(
                    "intent",
                    {"message": "question" if line.endswith("?") else "statement"},
                ),
                context,
            )
            for line in source.splitlines()
        )
        return ParseResult(
            events=tuple(
                dataclasses.replace(
                    event,
                    evidence=dataclasses.replace(event.evidence, line_number=number),
                )
                for number, event in enumerate(events, start=1)
            ),
            parser_name=self.name,
            parser_version=self.version,
        )


async def test_non_reproducible_parsers_retain_events() -> None:
    parser = _Intent()
    source = "why?\nok\nhow?\n"
    result, (document,) = await _run(parser, source, "chat")
    document = _evidence(document)

    aggregator = parser.aggregator
    assert isinstance(aggregator, EvidenceAggregator)
    assert not aggregator.reproducible
    assert not aggregator.requires_source
    entries = [entry for group in document.groups for entry in group.evidence]
    assert [entry.message for entry in entries] == ["question", "statement", "question"]
    assert sum(len(entry.events) for entry in entries) == 3
    restored = await ParseEngine().materialize(parser, "ignored", (document,))
    assert restored == result.events

    # Retained events survive the canonical encoding.
    (decoded,) = parser.deserialize(parser.serialize((document,)))
    assert decoded == document
    assert await ParseEngine().materialize(parser, "ignored", (decoded,)) == (
        result.events
    )

    (group,) = document.groups
    first = group.evidence[0]
    forged_event = dataclasses.replace(first.events[0], attributes={"message": "x"})
    forged = dataclasses.replace(
        group,
        evidence=(
            dataclasses.replace(first, events=(forged_event, *first.events[1:])),
            *group.evidence[1:],
        ),
    )
    with pytest.raises(IntegrityError):
        await ParseEngine().materialize(
            parser, "ignored", (dataclasses.replace(document, groups=(forged,)),)
        )
    with pytest.raises(ValueError, match="retained events must match"):
        dataclasses.replace(first, events=first.events * 2, sequence=first.sequence * 2)


async def test_mixed_content_splits_aggregates_and_dispatches_messages() -> None:
    source = 'intro\n{"a": 1,\n "b": [2]}\n2026-10-01T08:00:00Z ERROR x\n'
    parser = MixedContentParser()
    result, aggregates = await _run(parser, source, "mixed")

    assert [item.event_type for item in aggregates] == ["other", "log"]
    assert all(_evidence(item).parser_name == "mixed-content" for item in aggregates)
    # Fallback events carry their text; the log fallback its level and message.
    assert rows(aggregates[0]) == [
        (None, {"text": "intro"}, "1", 1),
        (None, {"text": '{"a": 1,'}, "2", 1),
        (None, {"text": ' "b": [2]}'}, "3", 1),
    ]
    assert rows(aggregates[1]) == [("ERROR", "x", "4", 1)]
    assert parser.aggregator.requires_source
    assert await ParseEngine().materialize(parser, source, aggregates) == result.events


async def test_custom_message_function() -> None:
    aggregator = EvidenceAggregator(
        reproducible=True,
        message=lambda event: event.attributes["message"].upper(),  # type: ignore[union-attr]
    )
    (document,) = await aggregator.aggregate([_event(1, "a"), _event(2, "a")])
    assert document.groups[0].evidence == (EvidenceEntry("A", 2, (1, 2)),)
    with pytest.raises(TypeError):
        EvidenceAggregator(message="nope")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        EvidenceAggregator(reproducible=1)  # type: ignore[arg-type]


async def test_aggregates_round_trip_through_the_parser_wire_format() -> None:
    parser = TimestampedLogParser()
    result, aggregates = await _run(parser, LOG)
    text = parser.serialize(aggregates)
    assert json.loads(text)["format"] == FORMAT == "parsefabric.aggregates/1"
    assert "kind" not in json.loads(text)["aggregates"][0]
    assert " " not in text.replace("db timeout", "").replace("service started", "")
    restored = parser.deserialize(text)
    assert restored == aggregates
    assert parser.deserialize(text.encode()) == aggregates
    assert parser.deserialize(parser.serialize(aggregates, indent=2)) == aggregates
    # The format is the same for every parser, so any parser decodes it.
    assert JSONParser().deserialize(text) == aggregates
    assert await ParseEngine().materialize(parser, LOG, restored) == result.events


async def test_serialization_is_closed_to_parser_evidence() -> None:
    events = (await TimestampedLogParser().parse(LOG)).events
    counts = await EventAggregator(group_by=("message",)).aggregate(events)
    assert all(isinstance(item, CountAggregate) for item in counts)
    with pytest.raises(TypeError, match="only EvidenceAggregate"):
        TimestampedLogParser().serialize(counts)  # type: ignore[arg-type]
    # Lossy counts keep their own plain JSON form, outside the parser format.
    assert tuple(CountAggregate.from_dict(item.to_dict()) for item in counts) == counts
    assert not hasattr(Aggregate, "kind")


async def test_grouped_documents_cannot_be_merged() -> None:
    _, (document,) = await _run(TimestampedLogParser(), LOG)
    aggregator = EvidenceAggregator()

    assert await aggregator.merge([document]) == (document,)
    with pytest.raises(CapabilityError):
        await aggregator.merge([document, document])


async def test_aggregate_rejects_mixed_sources_and_out_of_order_events() -> None:
    first = ParsedEvent("x", {}, evidence=Evidence(source_id="a", line_number=2))
    other = ParsedEvent("x", {}, evidence=Evidence(source_id="b", line_number=3))
    earlier = ParsedEvent("x", {}, evidence=Evidence(source_id="a", line_number=1))
    aggregator = EvidenceAggregator()

    with pytest.raises(ValueError, match="separately"):
        await aggregator.aggregate([first, other])
    with pytest.raises(ValueError, match="source order"):
        await aggregator.aggregate([first, earlier])


async def test_statistical_aggregation_is_lossy_and_not_materializable() -> None:
    aggregator = EventAggregator()
    assert not aggregator.lossless
    with pytest.raises(CapabilityError):
        await aggregator.materialize(())
