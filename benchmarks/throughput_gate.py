"""Repeated, explicitly scoped throughput gate for the native execution backends."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import sys
import time
from collections.abc import Iterator

from benchmarks._support import run_sync
from parsefabric.builtins import ApplicationLogParser
from parsefabric.execution import (
    AsyncExecutionBackend,
    ExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.models import ParseContext, ParseResult
from parsefabric.partitioning import LinePartitioner, Partition


def parse_partition(partition: Partition) -> ParseResult:
    return run_sync(
        ApplicationLogParser().parse(
            partition.content,
            ParseContext(
                partition_id=partition.partition_id,
                source_offset=partition.start_offset,
            ),
        )
    )


def records(count: int) -> Iterator[str]:
    for index in range(count):
        yield f"request {index} timeout"


async def trial(
    backend: ExecutionBackend,
    *,
    count: int,
    partition_lines: int,
    max_in_flight: int,
) -> float:
    partitioner = LinePartitioner(max_lines=partition_lines)
    parser = ApplicationLogParser()
    start = time.perf_counter()
    event_count = 0
    async for result in backend.map(
        parse_partition,
        partitioner.partition(records(count), capabilities=parser.capabilities),
        max_in_flight=max_in_flight,
    ):
        event_count += len(result.events)
    elapsed = time.perf_counter() - start
    if event_count != count:
        raise RuntimeError(f"expected {count} events, got {event_count}")
    return elapsed


async def benchmark(
    *,
    backend_name: str,
    count: int,
    partition_lines: int,
    workers: int,
    max_in_flight: int,
    warmups: int,
    samples: int,
    minimum: float | None,
) -> dict[str, object]:
    if backend_name == "async":
        backend: ExecutionBackend = AsyncExecutionBackend()
    elif backend_name == "thread":
        backend = ThreadExecutionBackend(max_workers=workers)
    elif backend_name == "process":
        backend = ProcessExecutionBackend(max_workers=workers)
    else:
        raise ValueError(f"unsupported execution backend: {backend_name}")
    async with backend:
        for _ in range(warmups):
            await trial(
                backend,
                count=count,
                partition_lines=partition_lines,
                max_in_flight=max_in_flight,
            )
        elapsed_samples = [
            await trial(
                backend,
                count=count,
                partition_lines=partition_lines,
                max_in_flight=max_in_flight,
            )
            for _ in range(samples)
        ]

    rates = [count / elapsed for elapsed in elapsed_samples]
    passed = minimum is None or all(rate >= minimum for rate in rates)
    return {
        "backend": backend_name,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "available_cpus": os.cpu_count(),
        "records": count,
        "partition_lines": partition_lines,
        "workers": workers if backend_name != "async" else 1,
        "max_in_flight": max_in_flight,
        "warmups": warmups,
        "samples": samples,
        "elapsed_seconds": elapsed_samples,
        "records_per_second": rates,
        "minimum_observed_records_per_second": min(rates),
        "median_records_per_second": statistics.median(rates),
        "required_minimum_records_per_second": minimum,
        "passed": passed,
    }


def positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def nonnegative_int(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return result


def positive_rate(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend", choices=("async", "thread", "process"), required=True
    )
    parser.add_argument("--records", type=positive_int, default=100_000)
    parser.add_argument("--partition-lines", type=positive_int, default=1_000)
    parser.add_argument("--workers", type=positive_int, default=2)
    parser.add_argument("--max-in-flight", type=positive_int, default=4)
    parser.add_argument("--warmups", type=nonnegative_int, default=1)
    parser.add_argument("--samples", type=positive_int, default=5)
    parser.add_argument("--min-records-per-second", type=positive_rate)
    args = parser.parse_args()
    result = asyncio.run(
        benchmark(
            backend_name=args.backend,
            count=args.records,
            partition_lines=args.partition_lines,
            workers=args.workers,
            max_in_flight=args.max_in_flight,
            warmups=args.warmups,
            samples=args.samples,
            minimum=args.min_records_per_second,
        )
    )
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
