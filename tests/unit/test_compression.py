"""Compression metrics compare a source with application-encoded output."""

from __future__ import annotations

import asyncio
import json

import pytest

from parsefabric import (
    CompressionMetrics,
    EvidenceAggregate,
    ParseContext,
    measure_compression,
)
from parsefabric.aggregation import Aggregate
from parsefabric.builtins import TimestampedLogParser
from parsefabric.compression import estimate_tokens
from parsefabric.engine import ParseEngine

LOG = "".join(
    f"2026-10-01T08:00:{index % 60:02d}Z ERROR db timeout on shard {index // 50}\n"
    for index in range(200)
)


def _aggregates(source: str) -> tuple[Aggregate, ...]:
    async def run() -> tuple[Aggregate, ...]:
        engine = ParseEngine()
        parser = TimestampedLogParser()
        result = await engine.parse(parser, source, ParseContext(source_id="ops"))
        return await engine.aggregate(parser, result.events)

    return asyncio.run(run())


def _encode(aggregates: tuple[Aggregate, ...]) -> str:
    """An application's own compact encoding of evidence aggregates."""
    documents = []
    for item in aggregates:
        assert isinstance(item, EvidenceAggregate)
        documents.append(
            {
                "event_type": item.event_type,
                "parser_name": item.parser_name,
                "count": item.count,
                "groups": [
                    {
                        "severity": group.severity,
                        "evidence": [
                            [entry.message, entry.occurrences, entry.positions]
                            for entry in group.evidence
                        ],
                    }
                    for group in item.groups
                ],
                "events_sha256": item.events_sha256,
            }
        )
    return json.dumps(documents, separators=(",", ":"))


def test_measures_application_output_against_utf8_input() -> None:
    aggregates = _aggregates(LOG)
    wire = _encode(aggregates)
    metrics = measure_compression(LOG, wire)

    assert isinstance(metrics, CompressionMetrics)
    assert metrics.input_bytes == len(LOG.encode())
    assert metrics.output_bytes == len(wire.encode())
    assert metrics.bytes_saved == metrics.input_bytes - metrics.output_bytes
    assert metrics.reduction_percent is not None
    assert metrics.reduction_percent > 85
    assert metrics.input_tokens == estimate_tokens(LOG)
    assert metrics.output_tokens == estimate_tokens(wire)
    assert sum(item.count for item in aggregates) == 200


def test_small_inputs_report_negative_savings_honestly() -> None:
    source = "2026-10-01T08:00:00Z INFO up\n"
    metrics = measure_compression(source, _encode(_aggregates(source)))
    assert metrics.bytes_saved < 0
    assert metrics.reduction_percent is not None
    assert metrics.reduction_percent < 0


def test_empty_input_has_no_percentages() -> None:
    metrics = measure_compression("", "[]")
    assert metrics.output_bytes == 2
    assert metrics.reduction_percent is None
    assert metrics.token_reduction_percent is None


def test_custom_token_estimator_and_bytes_input_and_output() -> None:
    wire = _encode(_aggregates(LOG))
    metrics = measure_compression(
        LOG.encode(), wire.encode(), token_estimator=lambda text: len(text.split())
    )
    assert metrics.input_tokens == len(LOG.split())
    assert metrics.output_bytes == len(wire.encode())


def test_estimate_tokens_rounds_up_utf8_bytes() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("\u00e9") == 1


def test_bytes_are_estimated_from_their_length_even_when_not_utf8() -> None:
    metrics = measure_compression(b"\xff" * 400, b"\xc3\xa9")
    assert (metrics.input_bytes, metrics.input_tokens) == (400, 100)
    assert (metrics.output_bytes, metrics.output_tokens) == (2, 1)
    seen: list[str] = []
    measure_compression(b"\xffok", "x", token_estimator=lambda t: seen.append(t) or 0)
    assert seen == ["\ufffdok", "x"]


@pytest.mark.parametrize("bad", [None, 3, ["x"]])
def test_rejects_invalid_source(bad: object) -> None:
    with pytest.raises(TypeError, match="source"):
        measure_compression(bad, "")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [None, (), ["x"]])
def test_rejects_unencoded_output(bad: object) -> None:
    with pytest.raises(TypeError, match="output"):
        measure_compression("x", bad)  # type: ignore[arg-type]
