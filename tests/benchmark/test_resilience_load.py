"""Load gates compare exact output and enforce the configured thresholds."""

from typing import Any

import pytest

from benchmarks.resilience_load import _percentile, run


async def test_load_checks_complete_fingerprints_across_native_backends() -> None:
    result = await run(documents=3, records=4, workers=2, samples=2)
    assert result["passed"] is True
    rows = result["measurements"]
    assert isinstance(rows, list)
    assert len(rows) == 6
    assert len({row["digest"] for row in rows}) == 1
    assert all(row["records"] == 12 for row in rows)


async def test_load_missed_rate_and_memory_targets_fail_explicitly() -> None:
    result = await run(
        documents=1,
        records=1,
        workers=1,
        samples=1,
        minimum_rate=1e100,
        maximum_peak_mib=1e-10,
    )
    assert result["passed"] is False


@pytest.mark.parametrize("option", ["documents", "records", "workers", "samples"])
async def test_load_rejects_invalid_integer_budgets(option: str) -> None:
    with pytest.raises(ValueError):
        await run(**{option: 0})


@pytest.mark.parametrize("option", ["minimum_rate", "maximum_peak_mib", "deadline"])
async def test_load_rejects_nonfinite_thresholds(option: str) -> None:
    changes: dict[str, Any] = {option: float("inf")}
    with pytest.raises(ValueError):
        await run(**changes)


def test_latency_percentiles_include_single_sample_and_interpolation() -> None:
    assert _percentile([3.0], 0.99) == 3
    assert _percentile([1, 3], 0.95) == pytest.approx(2.9)
