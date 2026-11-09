"""Compression metrics compare a source with application-encoded output."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from parsefabric import (
    CompressionMetrics,
    EvidenceAggregate,
    ParseContext,
    measure_compression,
)
from parsefabric.builtins import TimestampedLogParser
from parsefabric.compression import DEFAULT_TOKENIZER, ApproximateTokenizer, Tokenizer
from parsefabric.engine import ParseEngine

if TYPE_CHECKING:
    from parsefabric.aggregation import Aggregate

LOG = "".join(
    f"2026-10-01T08:00:{index % 60:02d}Z ERROR db timeout on shard {index // 50}\n"
    for index in range(200)
)


async def _aggregates(source: str) -> tuple[Aggregate, ...]:
    engine = ParseEngine()
    parser = TimestampedLogParser()
    result = await engine.parse(parser, source, ParseContext(source_id="ops"))
    return await engine.aggregate(parser, result.events)


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


async def test_measures_application_output_against_utf8_input() -> None:
    aggregates = await _aggregates(LOG)
    wire = _encode(aggregates)
    metrics = await measure_compression(LOG, wire)

    assert isinstance(metrics, CompressionMetrics)
    assert metrics.input_bytes == len(LOG.encode())
    assert metrics.output_bytes == len(wire.encode())
    assert metrics.bytes_saved == metrics.input_bytes - metrics.output_bytes
    assert metrics.reduction_percent is not None
    assert metrics.reduction_percent > 85
    assert metrics.input_tokens == await DEFAULT_TOKENIZER.count(LOG)
    assert metrics.output_tokens == await DEFAULT_TOKENIZER.count(wire)
    assert sum(item.count for item in aggregates) == 200


async def test_small_inputs_report_negative_savings_honestly() -> None:
    source = "2026-10-01T08:00:00Z INFO up\n"
    metrics = await measure_compression(source, _encode(await _aggregates(source)))
    assert metrics.bytes_saved < 0
    assert metrics.reduction_percent is not None
    assert metrics.reduction_percent < 0


async def test_empty_input_has_no_percentages() -> None:
    metrics = await measure_compression("", "[]")
    assert metrics.output_bytes == 2
    assert metrics.reduction_percent is None
    assert metrics.token_reduction_percent is None


class WordTokenizer(Tokenizer):
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def count(self, text: str) -> int:
        self.seen.append(text)
        return len(text.split())


async def test_custom_tokenizer_counts_text_and_decoded_bytes() -> None:
    wire = _encode(await _aggregates(LOG))
    tokenizer = WordTokenizer()
    metrics = await measure_compression(LOG.encode(), wire.encode(), tokenizer=tokenizer)
    assert metrics.input_tokens == len(LOG.split())
    assert metrics.output_bytes == len(wire.encode())
    tokenizer.seen.clear()
    await measure_compression(b"\xffok", "x", tokenizer=tokenizer)
    assert tokenizer.seen == ["\ufffdok", "x"]


async def test_approximate_tokenizer_rounds_up_utf8_bytes() -> None:
    assert await DEFAULT_TOKENIZER.count("") == 0
    assert await DEFAULT_TOKENIZER.count("abcde") == 2
    assert await DEFAULT_TOKENIZER.count("\u00e9") == 1
    assert DEFAULT_TOKENIZER.bytes_per_token == 4
    assert await ApproximateTokenizer(1).count("abc") == 3


@pytest.mark.parametrize("bad", [0, -1, True, 2.5, "4"])
def test_approximate_tokenizer_rejects_invalid_ratios(bad: object) -> None:
    with pytest.raises(ValueError, match="bytes_per_token"):
        # pyrefly: ignore[bad-argument-type]
        ApproximateTokenizer(bad)


async def test_bytes_are_estimated_from_their_length_even_when_not_utf8() -> None:
    metrics = await measure_compression(b"\xff" * 400, b"\xc3\xa9")
    assert (metrics.input_bytes, metrics.input_tokens) == (400, 100)
    assert (metrics.output_bytes, metrics.output_tokens) == (2, 1)


@pytest.mark.parametrize("bad", [None, 3, ["x"]])
async def test_rejects_invalid_source(bad: object) -> None:
    with pytest.raises(TypeError, match="source"):
        # pyrefly: ignore[bad-argument-type]
        await measure_compression(bad, "")


@pytest.mark.parametrize("bad", [None, (), ["x"]])
async def test_rejects_unencoded_output(bad: object) -> None:
    with pytest.raises(TypeError, match="output"):
        # pyrefly: ignore[bad-argument-type]
        await measure_compression("x", bad)


async def test_rejects_a_tokenizer_that_is_not_a_tokenizer() -> None:
    with pytest.raises(TypeError, match="Tokenizer"):
        # pyrefly: ignore[bad-argument-type]
        await measure_compression("x", "y", tokenizer=len)
