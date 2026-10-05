"""Validate user-owned semantic parsing without a provider or network."""

import json
import sys
from typing import Any

import pytest
import semantic_llm
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import BaseMessage

from parsefabric import ParseContext
from parsefabric.engine import ParseEngine
from parsefabric.errors import ParseError, SummaryValidationError
from parsefabric.serialization import dumps_result, loads_result
from tests.support.summary_model import SummaryModel


def test_semantic_example_without_credentials_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PARSEFABRIC_LLM_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["semantic_llm.py"])

    semantic_llm.main()

    assert "Set PARSEFABRIC_LLM_API_KEY to run this example." in capsys.readouterr().out


class _CapturePrompts(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.prompts: list[list[BaseMessage]] = []

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        self.prompts.extend(messages)


async def test_final_summary_uses_source_facts_not_semantic_claims() -> None:
    capture = _CapturePrompts()
    invented = "All orders updated successfully; zero timeouts; root cause confirmed."
    model = SummaryModel(initial=invented, callbacks=[capture])
    result, semantic_aggregates = await semantic_llm.run(model, summarize=True)
    assert invented not in str(result.events[0].attributes["message"])
    assert result.llm_result
    assert invented not in result.llm_result
    assert len(capture.prompts) == 5
    system = str(capture.prompts[0][0].content)
    assert "not proof of execution" in system
    assert "specific lines that directly support" in system
    assert "Attribute operator notes as reports" in system
    assert "later failure" in system
    assert "only the statement's body lines, not fence delimiters" in system
    assert "Explicitly state the total occurrences" in system
    assert "do not leave the total implicit" in system
    assert "never borrow timestamps from neighboring records" in system
    assert "never widen a range over unrelated lines" in system
    source_prompt = str(capture.prompts[0][1].content)
    assert (
        '19: {"service":"shop","batch":"oct-01","state":"recovering"}\n'
        "20: 2026-10-01T08:00:04+00:00 INFO"
    ) in source_prompt
    summary_system = str(capture.prompts[3][0].content)
    assert "SQL statements do not prove execution" in summary_system
    assert "not independently verified source facts" in summary_system
    assert "statement event's own positions" in summary_system
    assert "never expand its citation" in summary_system
    assert "Explicitly state the total occurrences" in summary_system
    assert "do not leave the overall total implicit" in summary_system
    assert "Use grouping keys only to calculate totals" in summary_system
    assert "without discussing fence delimiters" in summary_system
    assert "never borrow timestamps from neighboring records" in summary_system
    assert "never widen a range over unrelated lines" in summary_system
    prompt = str(capture.prompts[3][1].content)
    assert invented not in prompt
    document = json.loads(prompt.split("<evidence>\n")[1].split("\n</evidence>")[0])
    facts = document["facts"]
    assert not any(item["event_type"] == "semantic_interpretation" for item in facts)
    entries = facts
    timeouts = [
        entry for entry in entries if entry["message"] == "shop database timeout"
    ]
    assert sum(entry["occurrences"] for entry in timeouts) == 3
    assert [position for entry in timeouts for position in entry["positions"]] == [
        15,
        16,
        24,
    ]
    assert timeouts[0]["timestamps_known"] is True
    assert timeouts[0]["timestamps"] == [
        [15, "2026-10-01T08:00:02+00:00"],
        [16, "2026-10-01T08:00:03+00:00"],
        [24, "2026-10-01T08:00:05+00:00"],
    ]
    assert "line 25: 2026-10-01T08:00:06+00:00" in result.llm_result
    assert "line 19: 2026-" not in result.llm_result
    assert "line 26: 2026-" not in result.llm_result
    note = next(
        entry
        for entry in entries
        if entry["message"]
        == {"text": "operator note: second pass found two delayed orders"}
    )
    assert note["positions"] == [23]
    sql_entries = [entry for entry in facts if entry["event_type"] == "sql_statement"]
    assert next(entry for entry in sql_entries if entry["message"] == "select")[
        "positions"
    ] == [13]
    fence_positions = [
        position
        for entry in facts
        if entry["event_type"] == "fence"
        for position in entry["positions"]
    ]
    assert fence_positions == [12, 14]
    restored = await ParseEngine().materialize(
        semantic_llm.IncidentSemanticParser(model),
        semantic_llm.SOURCE.read_text(encoding="utf-8"),
        semantic_aggregates,
        ParseContext(source_id=semantic_llm.SOURCE.name),
    )
    assert restored == result.events
    assert len(capture.prompts) == 5
    semantic_input = json.loads(
        str(capture.prompts[1][1].content)
        .split("<evidence>\n")[1]
        .split("\n</evidence>")[0]
    )
    assert semantic_input["draft"] == invented
    recovering = next(
        fact for fact in semantic_input["facts"] if fact["positions"] == [19]
    )
    resumed = next(
        fact for fact in semantic_input["facts"] if fact["positions"] == [25]
    )
    assert recovering["timestamps"] == []
    assert resumed["timestamps"] == [[25, "2026-10-01T08:00:06+00:00"]]


async def test_semantic_events_are_retained_without_reinvoking_the_model() -> None:
    model = SummaryModel(label="Database timeout observed.")
    parser = semantic_llm.IncidentSemanticParser(model)
    source = "ERROR database timeout\nINFO recovered\n"
    context = ParseContext(source_id="incident", source_offset=9)
    result = await ParseEngine().parse(parser, source, context)
    assert not parser.capabilities.deterministic
    assert not parser.capabilities.parallel_safe
    assert result.llm_result is None
    (event,) = result.events
    message = event.attributes["message"]
    assert isinstance(message, str)
    assert "Database timeout observed." in message
    assert event.attributes["model_generated"] is True
    assert event.evidence.start_offset == 9
    assert event.evidence.end_offset == 9 + len(source.encode())
    assert event.evidence.source_id == "incident"
    assert event.evidence.parser_name == "semantic-incident"
    aggregates = await parser.aggregate(result.events)
    assert aggregates[0].retains_events
    assert (
        await ParseEngine().materialize(parser, source, aggregates, context)
        == result.events
    )
    assert model.i == 3
    assert loads_result(dumps_result(result)) == result


@pytest.mark.parametrize("summarize", [False, True])
async def test_semantic_example_final_result(summarize: bool) -> None:
    result, aggregates = await semantic_llm.run(
        SummaryModel(),
        summarize=summarize,
    )
    message = str(result.events[0].attributes["message"])
    assert "Evidence-based final summary" in message
    if summarize:
        assert result.llm_result
        assert "Evidence-based final summary" in result.llm_result
    else:
        assert result.llm_result is None
    assert sum(item.count for item in aggregates) == 1


async def test_semantic_example_rejects_invalid_input_and_empty_output() -> None:
    parser = semantic_llm.IncidentSemanticParser(FakeListChatModel(responses=[" "]))
    with pytest.raises(TypeError, match="text"):
        await parser.parse(1)
    with pytest.raises(ParseError, match="must not be empty"):
        await parser.parse("")
    with pytest.raises(ParseError, match="empty interpretation"):
        await parser.parse("ERROR timeout")


def test_semantic_cli_reports_review_failure_without_success_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise SummaryValidationError("Unsupported recovery claim")

    import llm_summary_openai_compatible

    monkeypatch.setattr(
        llm_summary_openai_compatible, "build_model", lambda: SummaryModel()
    )
    monkeypatch.setattr(semantic_llm, "run", fail)
    monkeypatch.setattr(sys, "argv", ["semantic_llm.py", "--summarize"])
    with pytest.raises(SystemExit, match="Semantic review failed"):
        semantic_llm.main()
    assert capsys.readouterr().out == ""
