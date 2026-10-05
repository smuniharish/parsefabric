from dataclasses import replace

import pytest

from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    PythonTracebackParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import IntegrityError
from parsefabric.models import ParseContext
from parsefabric.parser import AsyncParser, DeterministicParser, SemanticParser
from parsefabric.patterns import RegexPattern
from tests.support.grouped import rows


@pytest.mark.parametrize(
    ("factory", "source"),
    [
        (ApplicationLogParser, "ERROR timeout\nINFO recovered\nERROR timeout"),
        (
            lambda **kwargs: DeterministicParser(
                [RegexPattern("state", r"^(?P<state>\w+)$", event_type="state")],
                name="states",
                **kwargs,
            ),
            "ready\nwaiting\nready",
        ),
        (JSONParser, '{"state": "ready"}'),
        (
            lambda **kwargs: CLIOutputParser(
                [RegexPattern("status", r"^STATUS (?P<value>\w+)$")],
                **kwargs,
            ),
            "STATUS ready\nSTATUS waiting\nSTATUS ready",
        ),
        (PythonTracebackParser, "ValueError: missing field"),
    ],
)
async def test_standalone_parsers_aggregate_losslessly(factory, source):
    context = ParseContext(source_id="input")
    engine = ParseEngine()
    parser = factory()
    result = await engine.parse(parser, source, context)
    documents = await engine.aggregate(parser, result.events)
    assert {document.event_type for document in documents} == {
        event.event_type for event in result.events
    }
    for document in documents:
        assert (document.source_id, document.parser_name) == ("input", parser.name)
    assert sum(document.count for document in documents) == len(result.events)
    assert sum(
        entry.occurrences
        for document in documents
        for group in document.groups
        for entry in group.evidence
    ) == len(result.events)
    materialized = await engine.materialize(parser, source, documents, context)
    assert materialized == result.events


def _custom(base):
    class Custom(base):
        def __init__(self, *, name: str) -> None:
            super().__init__(name=name)

        async def parse(self, source, context=None):
            return await JSONParser().parse(source, context)

    return Custom


@pytest.mark.parametrize("base", [SemanticParser, AsyncParser])
def test_custom_parser_bases_are_aggregatable(base):
    assert _custom(base)(name="custom").capabilities.aggregatable


@pytest.mark.parametrize("base", [SemanticParser, AsyncParser])
async def test_custom_parsers_aggregate_via_engine(base):
    custom = _custom(base)
    engine = ParseEngine()
    context = ParseContext(source_id="custom")
    source = '{"state":"ready"}'
    parser = custom(name="custom")
    result = await engine.parse(parser, source, context)
    (document,) = await engine.aggregate(parser, result.events)
    assert document.event_type == "json_record"
    assert document.count == 1
    assert rows(document) == [(None, {"value": {"state": "ready"}}, "1", 1)]
    (entry,) = document.groups[0].evidence
    # Non-reproducible aggregators retain each event instead of re-parsing.
    assert entry.events == result.events
    materialized = await engine.materialize(parser, source, (document,), context)
    assert materialized == result.events
    assert materialized[0].attributes["value"] == {"state": "ready"}


async def test_grouped_runs_round_trip_event_attributes() -> None:
    parser = DeterministicParser(
        [RegexPattern("state", r"^(?P<state>\w+)$", event_type="state")],
        name="states",
    )
    source = "ready\nready\nwaiting\nready"
    context = ParseContext(source_id="states.txt")
    result = await parser.parse(source, context)
    (document,) = await parser.aggregate(result.events)
    # Each entry carries the event's content; positions only record order.
    assert rows(document) == [
        (None, {"state": "ready"}, "1,2", 2),
        (None, {"state": "waiting"}, "3", 1),
        (None, {"state": "ready"}, "4", 1),
    ]
    assert document.groups[0].pattern == "state"
    assert not document.retains_events
    restored = await ParseEngine().materialize(parser, source, (document,), context)
    assert [event.attributes["state"] for event in restored] == [
        "ready",
        "ready",
        "waiting",
        "ready",
    ]


async def test_tampered_occurrence_count_fails_materialization() -> None:
    parser = DeterministicParser(
        [RegexPattern("state", r"^(?P<state>\w+)$", event_type="state")],
        name="states",
    )
    source = "ready"
    context = ParseContext(source_id="states.txt")
    (document,) = await parser.aggregate((await parser.parse(source, context)).events)
    (group,) = document.groups
    (entry,) = group.evidence
    with pytest.raises(ValueError, match="exactly one position"):
        replace(entry, occurrences=2)
    with pytest.raises(ValueError, match="add up to the aggregate count"):
        replace(
            document,
            groups=(
                replace(
                    group, evidence=(replace(entry, occurrences=2, positions=(1, 1)),)
                ),
            ),
        )

    tampered = replace(
        document,
        count=2,
        groups=(
            replace(group, evidence=(replace(entry, occurrences=2, positions=(1, 1)),)),
        ),
    )
    with pytest.raises(IntegrityError, match="do not match"):
        await ParseEngine().materialize(parser, source, (tampered,), context)
