from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from parsefabric.models import ParseContext
from parsefabric.serialization import dumps_result, loads_result


async def test_shared_runtime_fixture_preserves_mixed_result_and_evidence() -> None:
    result = await mixed_parser().parse(
        MIXED_SOURCE, ParseContext(source_id="mixed.txt", correlation_id="trace-1")
    )
    assert [event.event_type for event in result.events] == [
        "timeout",
        "error",
        "json_record",
        "metric",
        "fence",
        "code",
        "fence",
        "other",
    ]
    assert [event.evidence.parser_name for event in result.events] == [
        "application-log",
        "application-log",
        "json",
        "metrics",
        "mixed-content",
        "mixed-content",
        "mixed-content",
        "mixed-content",
    ]
    assert [event.evidence.line_number for event in result.events] == [
        1,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
    ]
    assert all(event.evidence.source_id == "mixed.txt" for event in result.events)
    assert all(event.evidence.correlation_id == "trace-1" for event in result.events)
    assert result.events[-1].attributes == {"text": "unknown note"}
    assert loads_result(dumps_result(result)) == result
