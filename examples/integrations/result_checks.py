"""Check reconstruction of evidence returned by a real runtime."""

from examples.integrations.sync_bridge import run_sync
from parsefabric.engine import ParseEngine
from parsefabric.models import ParseContext, ParseResult
from parsefabric.parser import Parser


def verify_materialization(
    parser: Parser, source: str, context: ParseContext, result: ParseResult
) -> None:
    engine = ParseEngine()
    aggregates = run_sync(engine.aggregate(parser, result.events))
    restored = run_sync(engine.materialize(parser, source, aggregates, context))
    if restored != result.events:
        raise AssertionError("remote event aggregation/materialization differs")
