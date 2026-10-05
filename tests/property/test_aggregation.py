"""Properties of lossless evidence aggregation, its wire format and merging."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
from collections import Counter
from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from parsefabric.aggregation import (
    CountAggregate,
    EventAggregator,
    EvidenceAggregate,
    EvidenceAggregator,
    canonical_event,
    codec,
)
from parsefabric.models import ParsedEvent
from tests.support.strategies import AWARE_DATETIMES, JSON_VALUES, document_events


def _run[T](coroutine: object) -> T:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def _checksum(events: list[ParsedEvent]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(canonical_event(event).encode("utf-8") + b"\n")
    return digest.hexdigest()


@given(document_events(), st.booleans())
def test_aggregates_are_exact_lossless_summaries(
    events: list[ParsedEvent], reproducible: bool
) -> None:
    aggregator = EvidenceAggregator(reproducible=reproducible)
    aggregates: tuple[EvidenceAggregate, ...] = _run(aggregator.aggregate(events))
    by_identity: dict[tuple[str, str | None], list[ParsedEvent]] = {}
    for event in events:
        by_identity.setdefault(
            (event.event_type, event.evidence.parser_name), []
        ).append(event)
    assert [(item.event_type, item.parser_name) for item in aggregates] == list(
        by_identity
    )
    for aggregate in aggregates:
        members = by_identity[(aggregate.event_type, aggregate.parser_name)]
        assert aggregate.count == len(members)
        assert aggregate.events_sha256 == _checksum(members)
        positions = Counter(
            position
            for group in aggregate.groups
            for entry in group.evidence
            for position in entry.positions
        )
        assert positions == Counter(event.evidence.line_number for event in members)
        stamps = [event.timestamp for event in members if event.timestamp]
        assert aggregate.first_seen == (min(stamps) if stamps else None)
        assert aggregate.last_seen == (max(stamps) if stamps else None)
        assert aggregate.retains_events is not reproducible


@given(document_events(), st.booleans(), st.randoms(use_true_random=False))
def test_serialized_aggregates_materialize_the_original_events(
    events: list[ParsedEvent], reproducible: bool, random: object
) -> None:
    aggregator = EvidenceAggregator(reproducible=reproducible)
    aggregates = _run(aggregator.aggregate(events))
    decoded = list(codec.decode(codec.encode(aggregates)))
    assert decoded == list(aggregates)
    random.shuffle(decoded)  # type: ignore[attr-defined]
    restored = _run(aggregator.materialize(decoded, events if reproducible else None))
    assert restored == tuple(events)


@given(document_events(max_size=12))
def test_materialize_rejects_any_altered_event(events: list[ParsedEvent]) -> None:
    from parsefabric.errors import IntegrityError

    aggregator = EvidenceAggregator(reproducible=True)
    aggregates = _run(aggregator.aggregate(events))
    for index, event in enumerate(events):
        altered = list(events)
        altered[index] = replace(event, severity=f"{event.severity}!")
        try:
            _run(aggregator.materialize(aggregates, altered))
        except IntegrityError:
            continue
        raise AssertionError("an altered event was accepted")


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["error", "warning"]),
            JSON_VALUES,
            st.none() | AWARE_DATETIMES,
        ),
        max_size=16,
    ),
    st.integers(min_value=0, max_value=16),
    st.integers(min_value=0, max_value=16),
)
def test_count_merging_is_associative_commutative_and_matches_whole(
    rows: list[tuple[str, object, object]], first: int, second: int
) -> None:
    aggregator = EventAggregator(group_by=("value",))
    events = [
        ParsedEvent(kind, {"value": value}, timestamp=timestamp)  # type: ignore[arg-type]
        for kind, value, timestamp in rows
    ]
    cut_a, cut_b = sorted((first % (len(events) + 1), second % (len(events) + 1)))
    parts = [events[:cut_a], events[cut_a:cut_b], events[cut_b:]]
    partials = [_run(aggregator.aggregate(part)) for part in parts]
    whole = _run(aggregator.aggregate(events))
    for order in itertools.permutations(partials):
        merged = _run(aggregator.merge([item for part in order for item in part]))
        assert merged == whole
    assert sum(item.count for item in whole) == len(events)
    assert all(isinstance(item, CountAggregate) for item in whole)
