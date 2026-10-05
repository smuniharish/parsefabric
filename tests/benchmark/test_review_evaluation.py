"""The evaluation harness measures outcomes without claiming semantic proof."""

import asyncio
import gc
from dataclasses import replace

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from benchmarks.review_evaluation import (
    CallCounter,
    evaluate,
    recorded_contract_discrepancies,
    report,
)
from parsefabric import Evidence, EvidenceAggregator, ParsedEvent
from parsefabric._summary_review import facts_for
from parsefabric.errors import SummaryValidationError
from parsefabric.summarization import EvidenceSummarizer
from tests.support.summary_model import SummaryModel


async def test_repeated_evaluation_with_offline_protocol_fixture() -> None:
    rows = await evaluate(
        lambda counter: SummaryModel(callbacks=[counter]), repetitions=3
    )
    assert len(rows) == 18
    assert all(row["status"] == "accepted" for row in rows)
    assert all(row["repair_drafts"] == 0 for row in rows)
    result = report(rows, model="offline-protocol-fixture")
    assert result["acceptance_rate"] == 1
    assert result["semantic_error_rate"] is None


async def test_evaluation_differentiates_explicit_rejection_from_success() -> None:
    rows = await evaluate(
        lambda counter: FakeListChatModel(
            responses=["invalid JSON"], callbacks=[counter]
        ),
        repetitions=1,
    )
    assert len(rows) == 6
    assert all(row["status"] == "validation_rejected" for row in rows)
    assert all(row["calls"] == 3 for row in rows)
    assert all(row["summary"] is None for row in rows)


async def test_evaluation_timeout_is_not_a_validation_rejection() -> None:
    rows = await evaluate(
        lambda counter: FakeListChatModel(
            responses=["invalid JSON"], sleep=0.1, callbacks=[counter]
        ),
        repetitions=1,
        run_timeout=0.001,
    )
    assert len(rows) == 6
    assert all(row["status"] == "timed_out" for row in rows)
    assert report(rows, model="slow-fixture")["accepted"] == 0


async def test_recorded_checks_reject_count_and_position_corruption() -> None:
    events = [
        ParsedEvent(
            "log",
            {"message": "timeout"},
            severity="ERROR",
            evidence=Evidence(source_id="s", line_number=1),
        )
    ]
    aggregates = await EvidenceAggregator().aggregate(events)
    facts = facts_for(aggregates)
    summary = await EvidenceSummarizer(SummaryModel()).summarize(aggregates)
    assert not recorded_contract_discrepancies(summary.text, facts)
    assert recorded_contract_discrepancies(
        summary.text.replace("lines 1", "lines 10"), facts
    )
    assert recorded_contract_discrepancies(
        summary.text.replace("1 occurrence", "2 occurrences"), facts
    )
    altered = (replace(facts[0], message="different"),)
    assert recorded_contract_discrepancies(summary.text, altered)


@pytest.mark.parametrize("repetitions", [0, -1, True])
async def test_evaluation_rejects_invalid_run_budgets(repetitions: int) -> None:
    with pytest.raises(ValueError):
        await evaluate(lambda _: SummaryModel(), repetitions=repetitions)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
async def test_evaluation_rejects_invalid_timeout(seconds: float) -> None:
    with pytest.raises(ValueError):
        await evaluate(lambda _: SummaryModel(), run_timeout=seconds)


def test_counter_defaults_and_empty_report_are_explicit() -> None:
    assert CallCounter().calls == 0
    assert report([], model="not-run")["runs"] == 0


async def test_multibatch_rejection_does_not_abandon_queued_coroutines(
    recwarn: pytest.WarningsRecorder,
) -> None:
    aggregates = await EvidenceAggregator().aggregate(
        [ParsedEvent(f"type-{index}") for index in range(6)]
    )
    with pytest.raises(SummaryValidationError):
        await EvidenceSummarizer(
            FakeListChatModel(responses=["invalid"], sleep=0.01),
            max_aggregates=2,
            max_concurrency=1,
            max_revisions=0,
        ).summarize(aggregates)
    await asyncio.sleep(0)
    gc.collect()
    await asyncio.sleep(0)
    assert not [
        warning for warning in recwarn if "never awaited" in str(warning.message)
    ]
