"""Adversarial model output must not bypass the grounded review workflow."""

import json
from datetime import datetime
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import BaseMessage

from parsefabric import Evidence, EvidenceAggregator, ParsedEvent
from parsefabric._summary_review import facts_for
from parsefabric.errors import SummaryValidationError
from parsefabric.summarization import EvidenceSummarizer
from tests.support.summary_model import SummaryModel


class _ReviewPrompts(AsyncCallbackHandler):
    def __init__(self) -> None:
        self.messages: list[list[BaseMessage]] = []

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        self.messages.extend(messages)


async def test_partial_reviews_share_whole_source_severity_inventory() -> None:
    capture = _ReviewPrompts()
    events = [
        ParsedEvent(
            "log",
            {"message": "timeout"},
            severity="ERROR",
            evidence=Evidence(line_number=line),
        )
        for line in (1, 2, 3)
    ]
    events.extend(
        [
            ParsedEvent("metric", {"value": 24}, evidence=Evidence(line_number=4)),
            ParsedEvent(
                "source_record", {"text": "note"}, evidence=Evidence(line_number=5)
            ),
        ]
    )
    aggregates = await EvidenceAggregator(reproducible=True).aggregate(events)
    result = await EvidenceSummarizer(
        SummaryModel(callbacks=[capture]), max_aggregates=2
    ).summarize(aggregates)
    assert result.batches == 2
    assert result.calls == 4
    for system, human in capture.messages:
        document = json.loads(
            str(human.content).split("<evidence>\n")[1].split("\n</evidence>")[0]
        )
        assert document["source_scope"] == {
            "partial": True,
            "severity_occurrences": {"ERROR": 3, "UNSPECIFIED": 2},
        }
        assert len(document["facts"]) <= 2
        assert "subset" in str(system.content)
    assert '"ERROR": 3' in result.text.splitlines()[0]
    assert result.text.count("Recorded severity inventory") == 1


async def test_critic_reviews_rendered_metadata_not_missing_inline_citations() -> None:
    capture = _ReviewPrompts()
    events = [
        ParsedEvent(
            "log",
            {"message": "database timeout"},
            severity="ERROR",
            timestamp=datetime.fromisoformat(timestamp),
            evidence=Evidence(source_id="s", parser_name="p", line_number=line),
        )
        for line, timestamp in (
            (15, "2026-10-01T08:00:02+00:00"),
            (16, "2026-10-01T08:00:03+00:00"),
            (24, "2026-10-01T08:00:05+00:00"),
        )
    ]
    aggregates = await EvidenceAggregator(reproducible=False).aggregate(events)
    model = FakeListChatModel(
        responses=[
            _claims(text="Database changes committed."),
            '{"issues": ["Timeout evidence does not establish committed changes."]}',
            _claims(),
            '{"issues": []}',
        ],
        callbacks=[capture],
    )
    summary = await EvidenceSummarizer(model).summarize(aggregates)
    assert summary.calls == 4
    for index in (1, 3):
        system, human = capture.messages[index]
        document = json.loads(
            str(human.content).split("<evidence>\n")[1].split("\n</evidence>")[0]
        )
        candidate = document["rendered_candidate"]
        assert "3 occurrences total" in candidate
        assert "lines 15, 16, 24" in candidate
        for line, second in ((15, "02"), (16, "03"), (24, "05")):
            assert f"line {line}: 2026-10-01T08:00:{second}+00:00" in candidate
        assert "Do not demand inline citations" in str(system.content)
    assert (
        "committed"
        in json.loads(
            str(capture.messages[1][1].content)
            .split("<evidence>\n")[1]
            .split("\n</evidence>")[0]
        )["rendered_candidate"]
    )
    assert (
        summary.text
        == json.loads(
            str(capture.messages[3][1].content)
            .split("<evidence>\n")[1]
            .split("\n</evidence>")[0]
        )["rendered_candidate"]
    )
    assert "committed" not in summary.text


async def test_interleaved_findings_render_occurrence_order_before_critique() -> None:
    capture = _ReviewPrompts()
    events = [
        ParsedEvent(
            "log",
            {"message": message},
            severity=severity,
            timestamp=datetime.fromisoformat(timestamp),
            evidence=Evidence(source_id="s", parser_name="p", line_number=line),
        )
        for line, message, severity, timestamp in (
            (15, "database timeout", "ERROR", "2026-10-01T08:00:02+00:00"),
            (16, "database timeout", "ERROR", "2026-10-01T08:00:03+00:00"),
            (20, "connection restored", "INFO", "2026-10-01T08:00:04+00:00"),
            (24, "database timeout", "ERROR", "2026-10-01T08:00:05+00:00"),
        )
    ]
    aggregates = await EvidenceAggregator(reproducible=False).aggregate(events)
    draft = json.dumps(
        {
            "claims": [
                {
                    "text": "Database timeout recorded.",
                    "evidence_ids": ["e0"],
                    "occurrences": 3,
                },
                {
                    "text": "Connection restoration reported.",
                    "evidence_ids": ["e1"],
                    "occurrences": 1,
                },
            ]
        }
    )
    summary = await EvidenceSummarizer(
        FakeListChatModel(responses=[draft, '{"issues": []}'], callbacks=[capture])
    ).summarize(aggregates)
    candidate = json.loads(
        str(capture.messages[1][1].content)
        .split("<evidence>\n")[1]
        .split("\n</evidence>")[0]
    )["rendered_candidate"]
    assert candidate == summary.text
    timeline = candidate.split("### Source-order occurrence timeline\n", 1)[1]
    assert [
        int(row.split("line ")[1].split("]")[0]) for row in timeline.splitlines()
    ] == [15, 16, 20, 24]
    assert timeline.index("connection restored") < timeline.rindex("database timeout")
    assert "2026-10-01T08:00:05+00:00" in timeline.splitlines()[-1]
    assert "3 occurrences total" in candidate


def _claims(
    text: str = "Database timeout was recorded.",
    ids: tuple[str, ...] = ("e0",),
    count: int = 3,
) -> str:
    return json.dumps(
        {"claims": [{"text": text, "evidence_ids": ids, "occurrences": count}]}
    )


async def _timeouts():
    events = [
        ParsedEvent(
            "log",
            {"message": "database timeout"},
            severity="ERROR",
            evidence=Evidence(source_id="s", parser_name="p", line_number=line),
        )
        for line in (15, 16, 24)
    ]
    return await EvidenceAggregator(reproducible=True).aggregate(events)


@pytest.mark.parametrize(
    "bad",
    [
        "not JSON",
        '{"claims": []}',
        _claims(ids=("unknown",)),
        _claims(ids=("e0", "e0"), count=6),
        _claims(count=2),
        _claims(text="At 08:00:03 the database timed out."),
        _claims(text="Database timeout [L15-L24]."),
        _claims(text="The resumed record was untimestamped."),
        _claims(text="The metric was 999."),
    ],
)
async def test_invalid_claims_are_revised_before_critique(bad: str) -> None:
    model = FakeListChatModel(responses=[bad, _claims(), '{"issues": []}'])
    result = await EvidenceSummarizer(model).summarize(await _timeouts())
    assert result.calls == 3
    assert "3 occurrences total" in result.text
    assert "lines 15, 16, 24" in result.text
    assert "15\N{EN DASH}24" not in result.text


async def test_critic_rejection_requires_revised_claims_and_another_review() -> None:
    model = FakeListChatModel(
        responses=[
            _claims(text="The updates committed successfully."),
            '{"issues": ["SQL text does not prove execution or commit."]}',
            _claims(),
            '{"issues": []}',
        ]
    )
    result = await EvidenceSummarizer(model).summarize(await _timeouts())
    assert result.calls == 4
    assert "committed" not in result.text


async def test_metric_stage_overclaim_is_revised_without_dropping_values() -> None:
    aggregate = await EvidenceAggregator(reproducible=True).aggregate(
        [
            ParsedEvent(
                "metric",
                {"name": "reconciliation_candidates", "value": value},
                evidence=Evidence(source_id="s", parser_name="p", line_number=line),
            )
            for line, value in ((5, 24), (22, 2))
        ]
    )

    def draft(text: str) -> str:
        return _claims(text=text, ids=("e0", "e1"), count=2)

    model = FakeListChatModel(
        responses=[
            draft(
                "Reconciliation-candidate metrics were recorded at different stages."
            ),
            '{"issues": ["The source does not label lifecycle stages."]}',
            draft("Reconciliation-candidate metric values were recorded."),
            '{"issues": []}',
        ]
    )
    summary = await EvidenceSummarizer(model).summarize(aggregate)
    assert summary.calls == 4
    assert "stages" not in summary.text
    assert '"value": 24' in summary.text
    assert '"value": 2' in summary.text
    assert "lines 5" in summary.text
    assert "lines 22" in summary.text


async def test_unselected_metrics_remain_visible_to_critic_and_reader() -> None:
    capture = _ReviewPrompts()
    events = [
        ParsedEvent("log", {"message": "failed"}, severity="ERROR"),
        ParsedEvent(
            "metric",
            {"name": "candidates", "value": 24},
            evidence=Evidence(line_number=5),
        ),
        ParsedEvent(
            "metric",
            {"name": "candidates", "value": 2},
            evidence=Evidence(line_number=22),
        ),
    ]
    aggregates = await EvidenceAggregator(reproducible=True).aggregate(events)
    summary = await EvidenceSummarizer(
        FakeListChatModel(
            responses=[_claims(text="Failure recorded.", count=1), '{"issues": []}'],
            callbacks=[capture],
        )
    ).summarize(aggregates)
    assert '"value": 24' in summary.text
    assert '"value": 2' in summary.text
    assert "lines 5" in summary.text
    assert "lines 22" in summary.text
    assert summary.text in str(capture.messages[1][1].content).replace(
        '\\"', '"'
    ).replace("\\n", "\n")


async def test_source_record_layout_is_owned_by_renderer_not_prose_repairs() -> None:
    capture = _ReviewPrompts()
    aggregates = await EvidenceAggregator(reproducible=True).aggregate(
        [ParsedEvent("metric", {"name": "candidates", "value": 24})]
    )
    summary = await EvidenceSummarizer(
        FakeListChatModel(
            responses=['{"claims": []}', '{"issues": []}'],
            callbacks=[capture],
        )
    ).summarize(aggregates)
    assert summary.text.splitlines()[2].startswith(
        "- Source record. **1 occurrence total**"
    )
    assert "- Source record. - **" not in summary.text
    assert "must not trigger prose revisions" in str(capture.messages[1][0].content)
    assert summary.calls == 2


async def test_supported_numeric_identifiers_are_not_rejected() -> None:
    aggregate = await EvidenceAggregator(reproducible=True).aggregate(
        [ParsedEvent("sql_statement", {"text": "UPDATE orders WHERE id = 4101"})]
    )
    result = await EvidenceSummarizer(
        FakeListChatModel(
            responses=[
                _claims(text="Statement targets order 4101.", count=1),
                '{"issues": []}',
            ]
        )
    ).summarize(aggregate)
    assert "order 4101" in result.text


async def test_context_support_does_not_inflate_finding_occurrences() -> None:
    events = [
        ParsedEvent(
            "log",
            {"message": "database timeout"},
            severity="ERROR",
            evidence=Evidence(line_number=line),
        )
        for line in (15, 16, 24)
    ]
    events.append(
        ParsedEvent(
            "log",
            {"message": "connection restored"},
            severity="INFO",
            evidence=Evidence(line_number=20),
        )
    )
    events.sort(key=lambda event: event.evidence.line_number or 0)
    aggregates = await EvidenceAggregator(reproducible=True).aggregate(events)
    draft = json.dumps(
        {
            "claims": [
                {
                    "text": "Timeouts were recorded around reported restoration.",
                    "evidence_ids": ["e0"],
                    "context_ids": ["e1"],
                    "occurrences": 3,
                }
            ]
        }
    )
    summary = await EvidenceSummarizer(
        FakeListChatModel(responses=[draft, '{"issues": []}'])
    ).summarize(aggregates)
    assert "3 occurrences total" in summary.text
    assert "4 occurrences total" not in summary.text
    assert "Context evidence (not additional occurrences)" in summary.text
    timeline = summary.text.split("### Source-order occurrence timeline\n")[1]
    assert timeline.count("line 20]") == 1


async def test_unresolved_criticism_raises_instead_of_returning_success() -> None:
    model = FakeListChatModel(
        responses=[
            _claims(),
            '{"issues": ["Unsupported claim."]}',
            _claims(),
            '{"issues": ["Still unsupported."]}',
        ]
    )
    with pytest.raises(SummaryValidationError, match="after 1 revisions"):
        await EvidenceSummarizer(model, max_revisions=1).summarize(await _timeouts())
    assert model.i == 0  # exactly four responses, no unbounded loop


async def test_zero_revisions_and_malformed_critic_fail_explicitly() -> None:
    with pytest.raises(SummaryValidationError, match="after 0 revisions"):
        await EvidenceSummarizer(
            FakeListChatModel(responses=[_claims(count=1)]), max_revisions=0
        ).summarize(await _timeouts())
    with pytest.raises(SummaryValidationError, match="Critic"):
        await EvidenceSummarizer(
            FakeListChatModel(responses=[_claims(), '{"approved": true}'])
        ).summarize(await _timeouts())


async def test_malformed_critique_is_repaired_within_existing_revision_budget() -> None:
    model = FakeListChatModel(
        responses=[_claims(), '{"approved": true}', _claims(), '{"issues": []}']
    )
    summary = await EvidenceSummarizer(model, max_revisions=1).summarize(
        await _timeouts()
    )
    assert summary.calls == 4
    assert "3 occurrences total" in summary.text


async def test_zero_labeled_errors_is_renderer_metadata_not_invented_claim() -> None:
    aggregates = await EvidenceAggregator().aggregate(
        [ParsedEvent("metric", {"value": 24}, evidence=Evidence(line_number=1))]
    )
    summary = await EvidenceSummarizer(
        FakeListChatModel(responses=['{"claims":[]}', '{"issues":[]}'])
    ).summarize(aggregates)
    assert "No severity-labeled errors or warnings were recorded." in summary.text
    assert "Source record." in summary.text
    assert "24" in summary.text


async def test_error_omission_cannot_be_approved_by_the_critic() -> None:
    aggregate = await EvidenceAggregator(reproducible=True).aggregate(
        [
            ParsedEvent("log", {"message": "running"}, severity="INFO"),
            ParsedEvent("log", {"message": "failed"}, severity="ERROR"),
        ]
    )
    with pytest.raises(SummaryValidationError, match="every error/warning"):
        await EvidenceSummarizer(
            FakeListChatModel(responses=[_claims(ids=("e0",), count=1)]),
            max_revisions=0,
        ).summarize(aggregate)


async def test_fence_marker_is_not_accepted_as_statement_evidence() -> None:
    aggregate = await EvidenceAggregator(reproducible=True).aggregate(
        [
            ParsedEvent("fence", {"text": "```sql"}, evidence=Evidence(line_number=12)),
            ParsedEvent(
                "sql_statement",
                {"message": "select"},
                evidence=Evidence(line_number=13),
            ),
            ParsedEvent("fence", {"text": "```"}, evidence=Evidence(line_number=14)),
        ]
    )
    with pytest.raises(SummaryValidationError, match="fence delimiters"):
        await EvidenceSummarizer(
            FakeListChatModel(responses=[_claims(ids=("e0",), count=1)]),
            max_revisions=0,
        ).summarize(aggregate)
    result = await EvidenceSummarizer(
        FakeListChatModel(
            responses=[
                _claims(text="A SELECT statement is present.", ids=("e2",), count=1),
                '{"issues": []}',
            ]
        )
    ).summarize(aggregate)
    assert "lines 13" in result.text
    assert "12" not in result.text
    assert "14" not in result.text


async def test_timestamp_metadata_is_rendered_only_from_retained_records() -> None:
    events = [
        ParsedEvent(
            "state", {"message": "recovering"}, evidence=Evidence(line_number=19)
        ),
        ParsedEvent(
            "log",
            {"message": "resumed"},
            timestamp=datetime.fromisoformat("2026-10-01T08:00:06+00:00"),
            evidence=Evidence(line_number=25),
        ),
    ]
    retained = await EvidenceAggregator(reproducible=False).aggregate(events)
    facts = facts_for(retained)
    assert facts[0].timestamps_known
    assert facts[0].timestamps == ()
    assert facts[1].timestamps_known
    result = await EvidenceSummarizer(
        FakeListChatModel(
            responses=[
                json.dumps(
                    {
                        "claims": [
                            {
                                "text": "Recovering state recorded.",
                                "evidence_ids": ["e0"],
                                "occurrences": 1,
                            },
                            {
                                "text": "Resumption reported.",
                                "evidence_ids": ["e1"],
                                "occurrences": 1,
                            },
                        ]
                    }
                ),
                '{"issues": []}',
            ]
        )
    ).summarize(retained)
    assert "line 25: 2026-10-01T08:00:06+00:00" in result.text
    assert "08:00:03" not in result.text
    compact = await EvidenceAggregator(reproducible=True).aggregate(events)
    assert all(not fact.timestamps_known for fact in facts_for(compact))


async def test_duplicate_aggregates_fail_before_any_model_call() -> None:
    (aggregate,) = await _timeouts()
    model = FakeListChatModel(responses=["must not run"])
    with pytest.raises(ValueError, match="double-count"):
        await EvidenceSummarizer(model).summarize((aggregate, aggregate))
    assert model.i == 0


async def test_disjoint_aggregate_runs_are_totaled_in_the_same_batch() -> None:
    aggregator = EvidenceAggregator(reproducible=True)
    first = await aggregator.aggregate(
        [
            ParsedEvent(
                "log",
                {"message": "database timeout"},
                severity="ERROR",
                evidence=Evidence(source_id="s", parser_name="p", line_number=line),
            )
            for line in (15, 16)
        ]
    )
    later = await aggregator.aggregate(
        [
            ParsedEvent(
                "log",
                {"message": "database timeout"},
                severity="ERROR",
                evidence=Evidence(source_id="s", parser_name="p", line_number=24),
            )
        ]
    )
    result = await EvidenceSummarizer(
        FakeListChatModel(responses=[_claims(), '{"issues": []}']),
        max_aggregates=2,
    ).summarize((*later, *first))
    assert (result.aggregates, result.batches, result.calls) == (2, 1, 2)
    assert "3 occurrences total" in result.text
    assert "lines 15, 16, 24" in result.text


async def test_empty_irrelevant_batch_is_reviewed_not_rendered_as_commentary() -> None:
    aggregate = await EvidenceAggregator(reproducible=True).aggregate(
        [ParsedEvent("sql_statement", {"message": "select"})]
    )
    summary = await EvidenceSummarizer(
        FakeListChatModel(responses=['{"claims": []}', '{"issues": []}']),
        task="Find failures.",
    ).summarize(aggregate)
    assert "Source record." in summary.text
    assert '"select"' in summary.text
    assert "no failures" not in summary.text.lower()
    assert summary.calls == 2
