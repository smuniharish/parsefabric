import json
import subprocess
import sys

import pytest

from tests.support.paths import ROOT

ROOT = ROOT


def run_gate(backend: str, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.throughput_gate",
            "--backend",
            backend,
            "--records",
            "25",
            "--partition-lines",
            "10",
            "--warmups",
            "0",
            "--samples",
            "2",
            "--min-records-per-second",
            target,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("backend_name", ["async", "thread", "process"])
def test_throughput_gate_checks_counts_and_threshold(backend_name: str) -> None:
    completed = run_gate(backend_name, "1")
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["passed"] is True
    assert len(result["elapsed_seconds"]) == 2
    assert len(result["records_per_second"]) == 2


def test_throughput_gate_fails_a_missed_target() -> None:
    completed = run_gate("async", "1e100")
    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["passed"] is False


def test_throughput_gate_rejects_nonfinite_target() -> None:
    completed = run_gate("async", "nan")
    assert completed.returncode == 2
    assert "finite and positive" in completed.stderr
