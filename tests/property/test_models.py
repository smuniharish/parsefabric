"""Properties of the result models and their strict JSON representations."""

from __future__ import annotations

import contextlib
import json
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from parsefabric import ParseIssue, ParseResult, PatternStatistic
from parsefabric._json import MAX_JSON_DEPTH, copy_json, loads
from parsefabric.errors import SerializationError
from parsefabric.models import Evidence, ParsedEvent
from parsefabric.serialization import dumps_result, iter_ndjson, loads_result
from tests.support.strategies import (
    IDENTIFIERS,
    JSON_VALUES,
    NAMES,
    TEXT,
    events,
    evidence,
)

ISSUES = st.builds(
    ParseIssue,
    error_type=NAMES,
    message=TEXT,
    source_id=IDENTIFIERS,
    input_index=st.none() | st.integers(min_value=0, max_value=1_000),
)
STATISTICS = st.lists(
    st.builds(PatternStatistic, NAMES, st.integers(min_value=0, max_value=10**6)),
    max_size=4,
    unique_by=lambda statistic: statistic.pattern_name,
)
RESULTS = st.builds(
    ParseResult,
    events=st.lists(events(), max_size=6).map(tuple),
    warnings=st.lists(TEXT, max_size=3).map(tuple),
    errors=st.lists(ISSUES, max_size=3).map(tuple),
    pattern_statistics=STATISTICS.map(tuple),
    parser_name=IDENTIFIERS,
    parser_version=IDENTIFIERS,
    correlation_id=IDENTIFIERS,
    llm_result=st.none() | TEXT.filter(str.strip),
)


@given(RESULTS)
def test_results_round_trip_exactly_through_json(result: ParseResult) -> None:
    payload = dumps_result(result)
    assert loads_result(payload) == result
    assert loads_result(payload.encode("utf-8")) == result
    assert dumps_result(loads_result(payload)) == payload
    assert ParseResult.from_dict(result.to_dict()) == result
    assert list(iter_ndjson([result])) == [payload + "\n"]


@given(evidence())
def test_evidence_round_trips_through_its_dictionary(value: Evidence) -> None:
    assert Evidence.from_dict(value.to_dict()) == value


@given(events())
def test_event_dictionaries_are_independent_copies(event: ParsedEvent) -> None:
    data = event.to_dict()
    assert ParsedEvent.from_dict(data) == event
    data["attributes"] = {"changed": True}
    assert ParsedEvent.from_dict(event.to_dict()) == event


@given(JSON_VALUES)
def test_copy_json_returns_an_equal_independent_value(value: Any) -> None:
    copied = copy_json(value)
    assert copied == value
    assert json.dumps(copied, sort_keys=True) == json.dumps(value, sort_keys=True)
    if isinstance(value, (list, dict)) and value:
        assert copied is not value


@given(st.integers(min_value=MAX_JSON_DEPTH + 1, max_value=MAX_JSON_DEPTH + 50))
def test_copy_json_rejects_values_nested_too_deeply(depth: int) -> None:
    value: Any = []
    for _ in range(depth - 1):
        value = [value]
    with pytest.raises(ValueError, match="nests deeper"):
        copy_json(value)


@given(st.text(max_size=200) | st.binary(max_size=200))
def test_result_decoder_fails_only_with_serialization_errors(
    payload: str | bytes,
) -> None:
    with contextlib.suppress(SerializationError):
        loads_result(payload)


_MUTATIONS = st.sampled_from(["drop", "add", "retype"])


@given(RESULTS, _MUTATIONS, st.data())
def test_mutated_result_documents_are_rejected_or_valid(
    result: ParseResult, mutation: str, data: st.DataObject
) -> None:
    document = result.to_dict()
    key = data.draw(st.sampled_from(sorted(document)))
    if mutation == "drop":
        del document[key]
    elif mutation == "add":
        document[data.draw(NAMES.filter(lambda name: name not in document))] = None
    else:
        replacement = data.draw(st.sampled_from([None, 1, "x", [], {}]))
        assume(replacement != document[key])
        document[key] = replacement
    try:
        decoded = loads_result(json.dumps(document))
    except SerializationError:
        return
    assert mutation == "retype"
    assert dumps_result(decoded) == json.dumps(
        document, ensure_ascii=False, separators=(",", ":")
    )


@given(st.dictionaries(NAMES, st.integers(), min_size=1, max_size=4), st.data())
def test_strict_decoder_rejects_duplicate_keys(
    fields: dict[str, int], data: st.DataObject
) -> None:
    key = data.draw(st.sampled_from(sorted(fields)))
    body = ",".join(f"{json.dumps(name)}:{value}" for name, value in fields.items())
    with pytest.raises(ValueError, match="duplicate"):
        loads(f"{{{body},{json.dumps(key)}:0}}")
