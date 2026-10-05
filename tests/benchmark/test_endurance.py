"""Duration and incremental report semantics are checked before long runs."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.endurance import run
from parsefabric.execution import AsyncExecutionBackend


async def test_endurance_runs_all_backends_and_writes_completed_report(
    tmp_path: Path,
) -> None:
    path = tmp_path / "progress.json"
    result = await run(report_path=path, duration=0.2, records=3, pause=0)
    assert result["status"] == "passed"
    assert result["elapsed_seconds"] >= 0.2
    assert result["records_verified"] == result["cycles"] * 9
    assert result["cycles"] >= 1
    assert result["fingerprint"]
    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert not path.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("duration", 0),
        ("duration", True),
        ("cycle_timeout", float("nan")),
        ("maximum_growth_mib", -1),
        ("records", True),
        ("workers", 0),
        ("pause", float("inf")),
        ("pause", -1),
    ],
)
async def test_endurance_rejects_invalid_configuration(
    tmp_path: Path, option: str, value: Any
) -> None:
    arguments: dict[str, Any] = {option: value}
    with pytest.raises(ValueError):
        await run(report_path=tmp_path / "invalid.json", **arguments)
    assert not (tmp_path / "invalid.json").exists()


async def test_endurance_cancellation_does_not_report_success(tmp_path: Path) -> None:
    path = tmp_path / "cancelled.json"
    task = asyncio.create_task(run(report_path=path, duration=30, records=2))
    try:
        async with asyncio.timeout(15):
            # The benchmark only reports progress through its report file.
            while not path.exists() or json.loads(path.read_text())["cycles"] < 1:  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert json.loads(path.read_text())["status"] == "cancelled"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_endurance_records_worker_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected worker failure")

    monkeypatch.setattr(AsyncExecutionBackend, "run", fail)
    path = tmp_path / "failed.json"
    with pytest.raises(RuntimeError, match="injected worker failure"):
        await run(report_path=path, duration=1, records=2)
    result = json.loads(path.read_text())
    assert result["status"] == "failed"
    assert result["error_type"] == "RuntimeError"
    assert result["cycles"] == 0
    assert result["records_verified"] == 0


async def test_endurance_enforces_cycle_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stall(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(10)
        raise AssertionError("cycle deadline should interrupt the worker")

    monkeypatch.setattr(AsyncExecutionBackend, "run", stall)
    path = tmp_path / "timeout.json"
    with pytest.raises(TimeoutError):
        await run(report_path=path, duration=1, cycle_timeout=0.01)
    result = json.loads(path.read_text())
    assert result["status"] == "failed"
    assert result["error_type"] == "TimeoutError"
    assert result["records_verified"] == 0
