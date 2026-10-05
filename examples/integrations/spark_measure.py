"""Correctness-checked, bounded throughput sample for the Spark example."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from time import perf_counter

from examples.integrations.spark_batch import MAX_RECORDS, SparkBatchParser, make_job
from examples.integrations.sync_bridge import run_sync
from parsefabric.builtins import ApplicationLogParser
from parsefabric.models import ParseContext


def measure_batch(
    parser: SparkBatchParser,
    entries: Sequence[tuple[str, ParseContext]],
    *,
    minimum_records_per_second: float | None = None,
    clock: Callable[[], float] = perf_counter,
) -> tuple[int, float, float]:
    """Measure Spark submission through collection; check every result first."""
    if not 1 <= len(entries) <= MAX_RECORDS:
        raise ValueError(f"measurement requires 1 to {MAX_RECORDS} records")
    if minimum_records_per_second is not None and (
        not math.isfinite(minimum_records_per_second) or minimum_records_per_second <= 0
    ):
        raise ValueError("minimum records per second must be finite and positive")

    jobs = [make_job(source, context) for source, context in entries]
    expected = [
        run_sync(ApplicationLogParser().parse(source, context))
        for source, context in entries
    ]
    started = clock()
    actual = parser.parse(jobs, partitions=2)
    elapsed = clock() - started
    if len(actual) != len(entries):
        raise AssertionError(
            f"Spark returned {len(actual)} records; expected {len(entries)}"
        )
    if actual != expected:
        raise AssertionError(
            "Spark batch results or evidence differ from local parsing"
        )
    if elapsed <= 0 or not math.isfinite(elapsed):
        raise ValueError("measurement clock must report positive finite elapsed time")
    rate = len(entries) / elapsed
    print(
        f"Spark batch sample: {len(entries)} records in {elapsed:.3f} s "
        f"({rate:.2f} records/s; local[2], submission through collection)",
        flush=True,
    )
    print(
        "Bounded synthetic sample; not a production throughput guarantee.", flush=True
    )
    if minimum_records_per_second is not None and rate < minimum_records_per_second:
        raise AssertionError(
            f"Spark batch rate {rate:.2f} records/s is below configured minimum "
            f"{minimum_records_per_second:.2f} records/s"
        )
    return len(entries), elapsed, rate
