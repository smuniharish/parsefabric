"""Opt-in tests against a real OpenAI-compatible model.

They run only when ``PARSEFABRIC_LLM_API_KEY`` is set, and use the optional
``PARSEFABRIC_LLM_BASE_URL`` and ``PARSEFABRIC_LLM_MODEL`` variables. Select
them with ``pytest -m live``. The key is read from the environment only.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

from parsefabric import ParseContext
from parsefabric.errors import SummaryValidationError
from parsefabric.summarization import EvidenceSummarizer

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("PARSEFABRIC_LLM_API_KEY"),
        reason="set PARSEFABRIC_LLM_API_KEY to run live model tests",
    ),
]


@pytest.fixture
async def model() -> AsyncIterator[Any]:
    from llm_summary_openai_compatible import open_model

    async with open_model() as configured:
        assert configured is not None
        yield configured


async def test_summary_of_a_real_incident_matches_its_recorded_evidence(
    model: Any,
) -> None:
    from llm_summary import SOURCE
    from mixed_custom_and_builtin import make_parser

    from benchmarks.review_evaluation import recorded_contract_discrepancies
    from parsefabric._summary_review import facts_for

    parser = make_parser(timestamped=True)
    source = SOURCE.read_text(encoding="utf-8")
    result = await parser.parse(source, ParseContext(source_id=SOURCE.name))
    aggregates = await parser.aggregate(result.events)
    summarizer = EvidenceSummarizer(model, max_aggregates=4, max_concurrency=2)
    try:
        summary = await summarizer.summarize(aggregates)
    except SummaryValidationError as error:
        pytest.fail(f"the model could not produce a checked summary: {error}")
    assert summary.batches == -(-summary.aggregates // 4)
    assert summary.calls >= 2 * summary.batches
    assert recorded_contract_discrepancies(summary.text, facts_for(aggregates)) == []
    annotated = await summarizer.summarize_result(result, aggregates)
    assert annotated.events == result.events
    assert annotated.llm_result


async def test_semantic_parser_keeps_model_output_as_retained_evidence(
    model: Any,
) -> None:
    import semantic_llm

    result, aggregates = await semantic_llm.run(model, summarize=False)
    assert result.events
    assert all(aggregate.retains_events for aggregate in aggregates)
