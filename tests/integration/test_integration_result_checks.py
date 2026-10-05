import pytest

from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from examples.integrations.result_checks import verify_materialization
from parsefabric.builtins import ApplicationLogParser
from parsefabric.engine import ParseEngine
from parsefabric.models import ParseContext
from parsefabric.parser import Parser


@pytest.mark.parametrize(
    ("parser", "source"),
    [
        (ApplicationLogParser(), "database timeout\nconnection refused"),
        (mixed_parser(), MIXED_SOURCE),
        (ApplicationLogParser(), "quiet line"),
    ],
)
async def test_remote_results_reconstruct_exact_ordered_evidence(
    parser: Parser, source: str
) -> None:
    context = ParseContext(
        source_id="sample.txt",
        correlation_id="trace-1",
        partition_id="part-2",
        source_offset=27,
    )
    result = await parser.parse(source, context)
    verify_materialization(parser, source, context, result)


async def test_materialization_verifier_rejects_missing_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing(*args: object, **kwargs: object) -> tuple[()]:
        return ()

    monkeypatch.setattr(ParseEngine, "materialize", missing)
    parser = mixed_parser()
    context = ParseContext(source_id="sample.txt")
    result = await parser.parse(MIXED_SOURCE, context)
    with pytest.raises(AssertionError, match="aggregation/materialization differs"):
        verify_materialization(parser, MIXED_SOURCE, context, result)
