"""Duration-based native stability check with durable incremental progress."""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import os
import platform
import time
import tracemalloc
from pathlib import Path
from typing import Literal, TypedDict

from benchmarks.resilience_load import JobResult, parse_and_verify
from parsefabric.execution import (
    AsyncExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)


class Progress(TypedDict):
    status: Literal["running", "passed", "failed", "cancelled"]
    python: str
    platform: str
    requested_seconds: float
    elapsed_seconds: float
    cycles: int
    records_verified: int
    fingerprint: str | None
    caller_current_bytes: int
    caller_peak_bytes: int
    maximum_growth_bytes: int
    error_type: str | None
    error_message: str | None


def write_progress(path: Path, state: Progress) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 4:
                raise
            # Windows readers can briefly hold a handle that prevents replacement.
            time.sleep(0.02)


async def run(
    *,
    report_path: Path,
    duration: float = 86400,
    records: int = 100,
    workers: int = 2,
    cycle_timeout: float = 60,
    maximum_growth_mib: float = 64,
    pause: float = 0.05,
) -> Progress:
    if any(
        isinstance(value, bool) or not math.isfinite(value) or value <= 0
        for value in (duration, cycle_timeout, maximum_growth_mib)
    ):
        raise ValueError(
            "duration, cycle timeout, and growth must be finite and positive"
        )
    if any(type(value) is not int or value < 1 for value in (records, workers)):
        raise ValueError("records and workers must be positive integers")
    if isinstance(pause, bool) or not math.isfinite(pause) or pause < 0:
        raise ValueError("pause must be finite and nonnegative")
    if not report_path.parent.is_dir():
        raise ValueError("report directory must already exist")
    started = time.monotonic()
    state = Progress(
        status="running",
        python=platform.python_version(),
        platform=platform.platform(),
        requested_seconds=duration,
        elapsed_seconds=0,
        cycles=0,
        records_verified=0,
        fingerprint=None,
        caller_current_bytes=0,
        caller_peak_bytes=0,
        maximum_growth_bytes=int(maximum_growth_mib * 1024**2),
        error_type=None,
        error_message=None,
    )
    write_progress(report_path, state)
    tracemalloc.start()
    baseline: int | None = None
    try:
        # Pools are reused for the entire duration; this tests accumulated state,
        # not merely repeated fresh-process startup.
        async with (
            AsyncExecutionBackend() as native_async,
            ThreadExecutionBackend(max_workers=workers) as threads,
            ProcessExecutionBackend(max_workers=workers) as processes,
        ):
            while time.monotonic() - started < duration:
                async with asyncio.timeout(cycle_timeout):
                    for backend in (native_async, threads, processes):
                        result: JobResult = await backend.run(
                            parse_and_verify, {"index": 0, "records": records}
                        )
                        if state["fingerprint"] is None:
                            state["fingerprint"] = result["digest"]
                        elif result["digest"] != state["fingerprint"]:
                            raise AssertionError("endurance event fingerprint changed")
                        state["records_verified"] += records
                state["cycles"] += 1
                if state["cycles"] % 10 == 0:
                    gc.collect()
                current, peak = tracemalloc.get_traced_memory()
                # Warm-up includes lazy executor/library initialization.
                if state["cycles"] == 10:
                    baseline = current
                if (
                    baseline is not None
                    and current - baseline > state["maximum_growth_bytes"]
                ):
                    raise AssertionError(
                        "traced caller allocation growth exceeded limit"
                    )
                state["caller_current_bytes"], state["caller_peak_bytes"] = (
                    current,
                    peak,
                )
                state["elapsed_seconds"] = time.monotonic() - started
                write_progress(report_path, state)
                await asyncio.sleep(pause)
        state["status"] = "passed"
    except asyncio.CancelledError as error:
        state["status"] = "cancelled"
        state["error_type"], state["error_message"] = type(error).__name__, str(error)
        raise
    except Exception as error:
        state["status"] = "failed"
        state["error_type"], state["error_message"] = type(error).__name__, str(error)
        raise
    finally:
        state["elapsed_seconds"] = time.monotonic() - started
        tracemalloc.stop()
        write_progress(report_path, state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=86400)
    parser.add_argument("--records", type=int, default=100)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--cycle-timeout", type=float, default=60)
    parser.add_argument("--maximum-growth-mib", type=float, default=64)
    parser.add_argument("--pause", type=float, default=0.05)
    options = parser.parse_args()
    result = asyncio.run(
        run(
            report_path=options.report,
            duration=options.duration,
            records=options.records,
            workers=options.workers,
            cycle_timeout=options.cycle_timeout,
            maximum_growth_mib=options.maximum_growth_mib,
            pause=options.pause,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
