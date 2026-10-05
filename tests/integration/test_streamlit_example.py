"""Exercise the optional playground against its checked-in sample inputs."""

import asyncio
import json
from collections import Counter
from collections.abc import Iterable
from itertools import product

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from streamlit.testing.v1 import AppTest
from ui_backend import (
    PARSERS,
    SAMPLES,
    PlaygroundOptions,
    build_parser,
    run_parse,
    sample_text,
    verify_lossless,
)

from parsefabric.aggregation import EvidenceAggregate
from parsefabric.builtins import JSONParser
from parsefabric.compression import measure_compression
from parsefabric.errors import ParseError
from tests.support.paths import ROOT
from tests.support.summary_model import SummaryModel

_EXAMPLES = ROOT / "examples"
# Parsing the large sample can exceed Streamlit's 3-second default on slow runners.
_APP_TIMEOUT = 60


def _app() -> AppTest:
    return AppTest.from_file(
        str(_EXAMPLES / "streamlit_app.py"), default_timeout=_APP_TIMEOUT
    )


_COMBINATIONS = [
    (sample, parser, fmt)
    for sample, parser in product(SAMPLES, PARSERS)
    for fmt in (
        ("ISO timestamp", "Bracketed timestamp")
        if parser.startswith(("Mixed:", "Timestamped logs"))
        else ("ISO timestamp",)
    )
]

_MIXED_COUNTS = {
    "Shop incident (mixed)": {
        "log": 7,
        "json_record": 4,
        "sql_statement": 8,
        "metric": 3,
        "other": 2,
        "fence": 2,
    },
    "Audit review (mixed)": {
        "log": 4,
        "json_record": 3,
        "sql_statement": 7,
        "metric": 2,
        "other": 1,
        "fence": 2,
    },
    "Inventory (custom log format)": {
        "log": 5,
        "json_record": 2,
        "sql_statement": 4,
        "metric": 1,
        "other": 1,
        "fence": 2,
    },
    "Large incident log": {
        "log": 510,
        "other": 576,
        "json_record": 120,
        "fence": 24,
        "code": 24,
    },
    "Timestamped operations": {"log": 11},
    "JSON incident record": {"json_record": 1},
}
_APPLICATION_COUNTS = {
    "Shop incident (mixed)": {"warning": 1, "timeout": 3, "error": 3},
    "Audit review (mixed)": {"timeout": 1, "error": 1, "warning": 1},
    "Inventory (custom log format)": {"error": 3},
    "Shop SQL statements": {},
    "Large incident log": {
        "warning": 120,
        "timeout": 44,
        "error": 150,
        "authorization_failure": 21,
        "oom": 21,
        "service_down": 21,
        "authentication_failure": 22,
        "connection_failure": 21,
    },
    "Timestamped operations": {"warning": 2, "timeout": 3, "error": 3, "retry": 2},
    "JSON incident record": {},
}


@pytest.mark.parametrize(("sample", "parser_name", "log_format"), _COMBINATIONS)
async def test_combination_outputs_against_sample_expectations(
    sample: str, parser_name: str, log_format: str
) -> None:
    source = sample_text(sample)
    options = PlaygroundOptions(parser_name, log_format, SAMPLES[sample])
    strict_log_ok = sample == "Timestamped operations" and log_format == "ISO timestamp"
    if (
        (parser_name == "Timestamped logs" and not strict_log_ok)
        or (parser_name == "Custom SQL" and sample != "Shop SQL statements")
        or (parser_name == PARSERS[0] and sample == "Shop SQL statements")
    ):
        with pytest.raises(ParseError):
            await run_parse(source, options)
        return
    result, aggregates = await run_parse(source, options)
    if parser_name.startswith("Mixed:"):
        if sample == "Shop SQL statements":
            expected = {"code": 63, "other": 3}
        else:
            expected = dict(_MIXED_COUNTS[sample])
            if parser_name == PARSERS[1] and "sql_statement" in expected:
                expected["code"] = expected.pop("sql_statement")
            if (
                sample == "Inventory (custom log format)"
                and log_format == "ISO timestamp"
            ):
                expected["other"] += expected.pop("log")
    elif parser_name == "Application logs":
        expected = _APPLICATION_COUNTS[sample]
    elif parser_name == "JSON":
        expected = (
            {"json_record": 1} if sample == "JSON incident record" else {"unparsed": 1}
        )
    elif parser_name == "Custom SQL":
        expected = {"sql_statement": 25}
    else:
        expected = {"log": 11}
    assert dict(Counter(event.event_type for event in result.events)) == expected
    assert len(result.errors) == int(
        parser_name == "JSON" and sample != "JSON incident record"
    )
    if result.errors:
        assert result.events[0].attributes == {"text": source}
    data = source.encode("utf-8")
    for event in result.events:
        assert event.evidence.source_id == SAMPLES[sample]
        start, end = event.evidence.start_offset, event.evidence.end_offset
        assert start is not None
        assert end is not None
        assert 0 <= start < end <= len(data)
        if event.evidence.parser_name == "timestamped-log":
            assert event.timestamp is not None
            assert event.timestamp.utcoffset() is not None
        if "text" in event.attributes:
            text = event.attributes["text"]
            assert isinstance(text, str)
            assert data[start:end].decode("utf-8").rstrip("\r\n") == text.rstrip("\r\n")
        if event.event_type == "fence":
            assert str(event.attributes["text"]).startswith("```")
    assert sum(item.count for item in aggregates) == len(result.events)
    assert await verify_lossless(source, options, aggregates) == len(result.events)
    assert result.llm_result is None


async def test_llm_opt_in_and_opt_out_keep_parsing_identical() -> None:
    source = sample_text("Shop incident (mixed)")
    plain, aggregates = await run_parse(source, PlaygroundOptions(PARSERS[0]))
    enabled, summarized_aggregates = await run_parse(
        source,
        PlaygroundOptions(PARSERS[0], llm_enabled=True, max_aggregates=2),
        model=SummaryModel(label="Evidence-based final summary"),
    )
    assert enabled.llm_result
    assert "Evidence-based final summary" in enabled.llm_result
    assert plain.llm_result is None
    assert enabled.events == plain.events
    assert enabled.errors == plain.errors
    assert summarized_aggregates == aggregates
    with pytest.raises(ValueError, match="configured LangChain model"):
        await run_parse(source, PlaygroundOptions(PARSERS[0], llm_enabled=True))
    with pytest.raises(ParseError, match="no aggregates"):
        await run_parse(
            "plain note",
            PlaygroundOptions("Application logs", llm_enabled=True),
            model=FakeListChatModel(responses=["must not be used"]),
        )


@pytest.mark.parametrize(("sample", "parser_name", "log_format"), _COMBINATIONS)
async def test_llm_opt_in_across_every_combination(
    sample: str, parser_name: str, log_format: str
) -> None:
    source = sample_text(sample)
    options = PlaygroundOptions(
        parser_name, log_format, SAMPLES[sample], llm_enabled=True, max_aggregates=2
    )
    strict_log_ok = sample == "Timestamped operations" and log_format == "ISO timestamp"
    incompatible = (
        (parser_name == "Timestamped logs" and not strict_log_ok)
        or (parser_name == "Custom SQL" and sample != "Shop SQL statements")
        or (parser_name == PARSERS[0] and sample == "Shop SQL statements")
    )
    empty = parser_name == "Application logs" and sample in {
        "Shop SQL statements",
        "JSON incident record",
    }
    model = SummaryModel(label="Final evidence summary")
    if incompatible or empty:
        with pytest.raises(ParseError):
            await run_parse(source, options, model=model)
        assert model.i == 0
        return
    result, aggregates = await run_parse(source, options, model=model)
    assert result.llm_result
    assert "Final evidence summary" in result.llm_result
    assert aggregates
    assert result.events
    assert result.to_dict()["llm_result"] == result.llm_result


def test_playground_shows_final_llm_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    import llm_summary_openai_compatible

    monkeypatch.setattr(
        llm_summary_openai_compatible,
        "build_model",
        lambda: SummaryModel(label="Shop database timeout"),
    )
    app = _app().run()
    app.toggle[0].set_value(True).run()
    app.number_input[0].set_value(2).run()
    app.button[0].click().run()
    assert not app.exception
    result = json.loads(app.code[3].value)
    assert "Shop database timeout" in result["llm_result"]
    assert "3 occurrences total" in result["llm_result"]
    assert "lines 15, 16, 24" in result["llm_result"]
    assert app.text[0].value == result["llm_result"]
    app.toggle[0].set_value(False).run()
    app.button[0].click().run()
    assert json.loads(app.code[3].value)["llm_result"] is None
    assert not app.text


def test_playground_llm_configuration_failure_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm_summary_openai_compatible

    monkeypatch.setattr(llm_summary_openai_compatible, "build_model", lambda: None)
    app = _app().run()
    app.button[0].click().run()
    assert app.metric
    app.toggle[0].set_value(True).run()
    app.button[0].click().run()
    assert "configured LangChain model" in app.exception[0].message
    assert not app.metric
    assert "latest" not in app.session_state


async def test_model_failure_is_not_returned_as_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from parsefabric.summarization import EvidenceSummarizer

    async def fail(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(EvidenceSummarizer, "summarize_result", fail)
    with pytest.raises(ParseError, match="LLM summarization failed: model unavailable"):
        await run_parse(
            sample_text("Shop incident (mixed)"),
            PlaygroundOptions(PARSERS[0], llm_enabled=True),
            model=FakeListChatModel(responses=["unused"]),
        )


def _occurrences(aggregates: Iterable[EvidenceAggregate]) -> int:
    return sum(
        entry.occurrences
        for aggregate in aggregates
        for group in aggregate.groups
        for entry in group.evidence
    )


def _entries(aggregates) -> int:
    return sum(len(group.evidence) for item in aggregates for group in item.groups)


def _aggregate_output(app: AppTest) -> list[EvidenceAggregate]:
    # One closed wire format: any parser deserializes any parser's output.
    return list(JSONParser().deserialize(_json_output(app, "Complete aggregates JSON")))


def _json_output(app: AppTest, label: str) -> str:
    for area in app.text_area:
        if area.label == label:
            assert area.disabled
            text = area.value
            assert isinstance(text, str)
            return text
    for code in app.code[1:]:
        value = json.loads(code.value)
        if (
            (
                label == "Complete aggregates JSON"
                and isinstance(value, dict)
                and "aggregates" in value
            )
            or (label == "Complete events JSON" and isinstance(value, list))
            or (
                label == "Complete ParseResult JSON"
                and isinstance(value, dict)
                and "llm_result" in value
            )
        ):
            return code.value
    raise AssertionError(f"missing output: {label}")


@pytest.mark.parametrize("size", [100_000, 100_001])
def test_large_json_rendering_threshold_preserves_complete_output(size: int) -> None:
    app = AppTest.from_string(
        "from streamlit_app import show_json_output\n"
        f"show_json_output('Test output', 'x' * {size})\n",
        default_timeout=_APP_TIMEOUT,
    ).run()
    assert not app.exception
    if size > 100_000:
        assert not app.code
        assert app.text_area[0].disabled
        assert app.text_area[0].value == "x" * size
    else:
        assert not app.text_area
        assert app.code[0].value == "x" * size
        assert app.code[0].show_line_numbers


def test_large_json_display_updates_between_parse_runs() -> None:
    app = _app().run()
    app.selectbox[0].set_value("Large incident log").run()
    app.button[1].click().run()
    app.button[0].click().run()
    first = json.loads(_json_output(app, "Complete ParseResult JSON"))
    assert first["events"][0]["evidence"]["source_id"] == "incident-mixed.log"
    app.text_input[0].set_value("second-large-run").run()
    app.button[0].click().run()
    assert not app.exception
    second = json.loads(_json_output(app, "Complete ParseResult JSON"))
    assert second["events"][0]["evidence"]["source_id"] == "second-large-run"
    assert len(second["events"]) == 1254
    aggregates = _aggregate_output(app)
    assert all(item.source_id == "second-large-run" for item in aggregates)
    events = json.loads(_json_output(app, "Complete events JSON"))
    assert all(event["evidence"]["source_id"] == "second-large-run" for event in events)


@pytest.mark.parametrize(("sample", "parser_name", "log_format"), _COMBINATIONS)
def test_all_sample_and_configuration_combinations_render_consistently(
    sample: str,
    parser_name: str,
    log_format: str,
) -> None:
    source = sample_text(sample)
    options = PlaygroundOptions(
        parser_name=parser_name,
        log_format=log_format,
        source_id=SAMPLES[sample],
    )
    result = None
    aggregates = ()
    verified = None
    try:
        result, aggregates = asyncio.run(run_parse(source, options))
        verified = asyncio.run(verify_lossless(source, options, aggregates))
    except (ParseError, ValueError, TypeError) as error:
        expected_error = str(error)
    else:
        expected_error = None

    app = _app().run()
    app.selectbox[0].set_value(sample).run()
    app.button[1].click().run()
    assert app.text_area[0].value == source
    assert app.text_input[0].value == SAMPLES[sample]
    assert app.code[0].value == "\n".join(source.splitlines())
    assert app.code[0].show_line_numbers
    app.selectbox[1].set_value(parser_name).run()
    if parser_name.startswith(("Mixed:", "Timestamped logs")):
        app.selectbox[2].set_value(log_format).run()
    assert len(app.toggle) == 1
    assert not app.toggle[0].value
    app.button[0].click().run()

    if expected_error is not None:
        assert app.exception
        assert expected_error in app.exception[0].message
        assert not app.metric
        assert len(app.code) == 1
        return
    assert result is not None
    assert verified == len(result.events)
    assert not app.exception
    assert [metric.value for metric in app.metric[:3]] == [
        str(len(result.events)),
        str(len(aggregates)),
        str(len(result.errors)),
    ]
    assert all(code.show_line_numbers for code in app.code)
    aggregate_data = list(aggregates)
    assert _aggregate_output(app) == aggregate_data
    assert json.loads(_json_output(app, "Complete events JSON")) == [
        event.to_dict() for event in result.events
    ]
    assert (
        json.loads(_json_output(app, "Complete ParseResult JSON")) == result.to_dict()
    )
    assert result.llm_result is None
    metrics = measure_compression(source, build_parser(options).serialize(aggregates))
    assert [metric.value for metric in app.metric[3:]] == [
        f"{metrics.input_bytes:,} B",
        f"{metrics.output_bytes:,} B",
        (
            f"{metrics.reduction_percent:+.1f}%"
            if metrics.reduction_percent is not None
            else "N/A"
        ),
        (
            f"{metrics.token_reduction_percent:+.1f}%"
            if metrics.token_reduction_percent is not None
            else "N/A"
        ),
    ]
    assert app.metric[3].label == "Input size (UTF-8)"
    assert app.metric[4].label == "Aggregate size (compact JSON)"
    assert app.metric[5].label == "Byte reduction"
    assert app.metric[6].label == "Token reduction (est.)"
    assert app.metric[5].delta == f"{metrics.bytes_saved:+,} B"
    assert app.metric[6].delta == f"{metrics.tokens_saved:+,} tokens"
    assert not app.success
    decoded = app.dataframe[0].value
    assert len(decoded) == _entries(aggregates)
    occurrences = int(decoded["occurrences"].sum()) if len(decoded) else 0
    assert occurrences == len(result.events)


@pytest.mark.parametrize(
    ("parser_name", "sample", "events", "event_types"),
    [
        (
            PARSERS[0],
            "Shop incident (mixed)",
            26,
            {"log", "json_record", "sql_statement", "metric", "other", "fence"},
        ),
        (
            PARSERS[1],
            "Shop incident (mixed)",
            26,
            {"log", "json_record", "metric", "other", "code", "fence"},
        ),
        (PARSERS[2], "Timestamped operations", 11, {"log"}),
        (PARSERS[3], "Timestamped operations", 10, None),
        (PARSERS[4], "JSON incident record", 1, {"json_record"}),
        (PARSERS[5], "Shop SQL statements", 25, {"sql_statement"}),
    ],
)
async def test_playground_presets(
    parser_name: str, sample: str, events: int, event_types: set[str] | None
) -> None:
    source = sample_text(sample)
    options = PlaygroundOptions(parser_name=parser_name, source_id="playground-fixture")
    result, aggregates = await run_parse(source, options)
    assert len(result.events) == events
    assert not result.errors
    assert all(
        event.evidence.source_id == "playground-fixture" for event in result.events
    )
    if event_types is not None:
        assert {document.event_type for document in aggregates} == event_types
    assert all(document.source_id == "playground-fixture" for document in aggregates)
    assert sum(document.count for document in aggregates) == events
    assert _occurrences(aggregates) == events
    assert await verify_lossless(source, options, aggregates) == events


async def test_playground_mixed_configuration_and_bad_input() -> None:
    source = "operator note: call support\n[2026-10-01T08:00:00+00:00] [ERROR] failed"
    options = PlaygroundOptions(
        parser_name=PARSERS[1],
        log_format="Bracketed timestamp",
    )
    result, aggregates = await run_parse(source, options)
    assert [event.event_type for event in result.events] == ["other", "log"]
    assert result.events[0].attributes == {"text": "operator note: call support"}
    assert [(item.event_type, item.count) for item in aggregates] == [
        ("other", 1),
        ("log", 1),
    ]
    assert await verify_lossless(source, options, aggregates) == 2
    with pytest.raises(ValueError, match="paste some input"):
        await run_parse("  ", options)
    with pytest.raises(ValueError, match="unknown parser"):
        await run_parse("valid input", PlaygroundOptions(parser_name="missing"))


async def test_large_file_backed_input_is_not_truncated() -> None:
    source = sample_text("Large incident log")
    result, aggregates = await run_parse(
        source, PlaygroundOptions(parser_name=PARSERS[1])
    )
    assert len(source.splitlines()) == len(result.events) == 1254
    assert sum(item.count for item in aggregates) == 1254
    assert not result.errors


async def test_json_parser_retains_incompatible_sample_as_one_original() -> None:
    source = sample_text("Shop incident (mixed)")
    result, aggregates = await run_parse(
        source, PlaygroundOptions(parser_name="JSON", source_id="mixed-source.txt")
    )
    assert len(result.events) == 1
    assert result.events[0].event_type == "unparsed"
    assert result.events[0].attributes == {"text": source}
    assert result.events[0].evidence.source_id == "mixed-source.txt"
    assert len(result.errors) == 1
    assert result.errors[0].error_type == "DecodeError"
    assert len(aggregates) == 1
    assert aggregates[0].count == 1


@pytest.mark.parametrize("parser_name", PARSERS[:2])
async def test_playground_mixed_parser_frames_pretty_json(parser_name: str) -> None:
    source = 'operator note\n{\n  "service": "shop",\n  "ok": true\n}\n'
    options = PlaygroundOptions(parser_name=parser_name)
    result, aggregates = await run_parse(source, options)
    assert not result.errors
    assert [event.event_type for event in result.events] == ["other", "json_record"]
    assert result.events[1].attributes == {"value": {"service": "shop", "ok": True}}
    assert result.events[1].evidence.line_number == 2
    assert result.events[1].evidence.end_offset == len(source.encode("utf-8"))
    assert [(item.event_type, item.count) for item in aggregates] == [
        ("other", 1),
        ("json_record", 1),
    ]
    assert await verify_lossless(source, options, aggregates) == 2


def test_streamlit_app_renders_and_reacts_to_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(_EXAMPLES))
    app = _app().run()
    assert not app.exception
    assert "ParseFabric playground" in app.title[0].value
    app.button[0].click().run()
    assert not app.exception
    assert [metric.value for metric in app.metric[:3]] == ["26", "6", "0"]
    size_before_edit = [metric.value for metric in app.metric[3:]]
    app.text_area[0].set_value("changed but not parsed yet").run()
    assert [metric.value for metric in app.metric[3:]] == size_before_edit
    source = sample_text("Shop incident (mixed)")
    app.text_area[0].set_value(source).run()
    assert app.subheader[2].value == "Grouped evidence"
    assert app.subheader[3].value == "Final aggregated output"
    assert app.subheader[4].value == "Parsed events and evidence"
    assert len(app.code) == 4
    assert all(code.show_line_numbers for code in app.code)
    mixed = _aggregate_output(app)
    assert sum(item.count for item in mixed) == 26
    assert _occurrences(mixed) == 26
    (sql_document,) = [item for item in mixed if item.parser_name == "sql-statements"]
    assert sql_document.count == 8
    assert len(json.loads(app.code[2].value)) == 26

    app.text_area[0].set_value("operator note: check the invoice").run()
    app.button[0].click().run()
    assert not app.exception
    assert [metric.value for metric in app.metric[:3]] == ["1", "1", "0"]

    app.selectbox[0].set_value("Timestamped operations").run()
    app.button[1].click().run()
    assert app.text_input[0].value == "timestamped-operations.log"
    app.selectbox[1].set_value("Timestamped logs").run()
    app.button[0].click().run()
    assert not app.exception
    assert [metric.value for metric in app.metric[:3]] == ["11", "1", "0"]
    (log_document,) = _aggregate_output(app)
    assert log_document.event_type == "log"
    assert log_document.count == 11
    assert _occurrences([log_document]) == 11
    log_source = (
        "2026-09-30T10:15:00+00:00 ERROR api database timeout on node-01\n"
        "2026-09-30T10:15:02+00:00 ERROR api database timeout on node-01"
    )
    app.text_area[0].set_value(log_source).run()
    app.button[0].click().run()
    (repeated,) = _aggregate_output(app)
    (group,) = repeated.groups
    assert group.severity == "ERROR"
    assert [(entry.message, entry.occurrences) for entry in group.evidence] == [
        ("api database timeout on node-01", 2)
    ]
    assert [
        event["attributes"]["message"] for event in json.loads(app.code[2].value)
    ] == [
        "api database timeout on node-01",
        "api database timeout on node-01",
    ]

    app.selectbox[0].set_value("Shop SQL statements").run()
    app.button[1].click().run()
    app.selectbox[1].set_value("Custom SQL").run()
    app.button[0].click().run()
    assert not app.exception
    (sql_only,) = _aggregate_output(app)
    assert sql_only.event_type == "sql_statement"
    assert _occurrences([sql_only]) == 25

    app.selectbox[1].set_value("JSON").run()
    app.text_area[0].set_value("{invalid json").run()
    app.button[0].click().run()
    assert not app.exception
    assert [metric.value for metric in app.metric[:3]] == ["1", "1", "1"]
    assert len(app.metric) == 7
    assert json.loads(app.code[2].value)[0]["attributes"] == {"text": "{invalid json"}
