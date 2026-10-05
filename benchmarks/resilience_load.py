"""Bounded sustained load with exact provenance and reconstruction assertions."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import platform
import statistics
import time
import tracemalloc
from collections.abc import Iterator
from typing import Literal, TypedDict

from parsefabric import ParseContext
from parsefabric.aggregation.evidence import canonical_event
from parsefabric.engine import ParseEngine
from parsefabric.execution import (
    AsyncExecutionBackend,
    ProcessExecutionBackend,
    ThreadExecutionBackend,
)
from parsefabric.parser import DeterministicParser
from parsefabric.patterns import RegexPattern

type BackendName = Literal["async", "thread", "process"]


class Job(TypedDict):
    index: int
    records: int


class JobResult(TypedDict):
    index: int
    digest: str
    seconds: float


class Sample(TypedDict):
    backend: BackendName
    records: int
    elapsed_seconds: float
    records_per_second: float
    caller_peak_traced_bytes: int
    document_p50_seconds: float
    document_p95_seconds: float
    document_p99_seconds: float
    digest: str


async def parse_and_verify(job: Job) -> JobResult:
    started = time.perf_counter()
    records = [
        f"request {index} timeout \u00e9\u65e5\u672c" if index % 3 else ""
        for index in range(job["records"])
    ]
    # The terminal LF ensures even a final blank record belongs to the input.
    source = "\r\n".join(records) + "\r\n"
    parser = DeterministicParser(
        [RegexPattern("record", r"^(?P<message>.*)$")], name="load-records"
    )
    engine = ParseEngine()
    context = ParseContext(source_id=f"document-{job['index']}")
    result = await engine.parse(parser, source, context)
    if len(result.events) != job["records"] or result.errors:
        raise AssertionError("load parse count or error contract failed")
    offset = 0
    for number, (event, raw) in enumerate(
        zip(result.events, source.splitlines(keepends=True), strict=True), start=1
    ):
        if (
            event.evidence.line_number != number
            or event.evidence.start_offset != offset
        ):
            raise AssertionError("load provenance does not match the input")
        offset += len(raw.encode("utf-8"))
        if event.evidence.end_offset != offset:
            raise AssertionError("load byte span does not match the input")
    aggregates = await engine.aggregate(parser, result.events)
    decoded = parser.deserialize(parser.serialize(aggregates))
    restored = await engine.materialize(parser, source, decoded, context)
    before = "\n".join(canonical_event(event) for event in result.events)
    after = "\n".join(canonical_event(event) for event in restored)
    if before != after:
        raise AssertionError("load reconstruction does not match every event")
    return JobResult(
        index=job["index"],
        digest=hashlib.sha256(before.encode("utf-8")).hexdigest(),
        seconds=time.perf_counter() - started,
    )


def _jobs(documents: int, records: int) -> Iterator[Job]:
    for index in range(documents):
        yield Job(index=index, records=records)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


async def measure(
    backend_name: BackendName,
    *,
    documents: int,
    records: int,
    workers: int,
) -> Sample:
    backend = (
        AsyncExecutionBackend()
        if backend_name == "async"
        else (
            ThreadExecutionBackend(max_workers=workers)
            if backend_name == "thread"
            else ProcessExecutionBackend(max_workers=workers)
        )
    )
    results: list[JobResult] = []
    tracemalloc.start()
    started = time.perf_counter()
    try:
        async with backend:
            results.extend(
                [
                    result
                    async for result in backend.map(
                        parse_and_verify,
                        _jobs(documents, records),
                        max_in_flight=workers,
                    )
                ]
            )
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if len(results) != documents or sorted(row["index"] for row in results) != list(
        range(documents)
    ):
        raise AssertionError("load execution lost or duplicated documents")
    latencies = [row["seconds"] for row in results]
    digest = hashlib.sha256(
        "".join(
            row["digest"] for row in sorted(results, key=lambda row: row["index"])
        ).encode()
    ).hexdigest()
    return Sample(
        backend=backend_name,
        records=documents * records,
        elapsed_seconds=elapsed,
        records_per_second=documents * records / elapsed,
        caller_peak_traced_bytes=peak,
        document_p50_seconds=statistics.median(latencies),
        document_p95_seconds=_percentile(latencies, 0.95),
        document_p99_seconds=_percentile(latencies, 0.99),
        digest=digest,
    )


async def run(
    *,
    documents: int = 100,
    records: int = 100,
    workers: int = 2,
    samples: int = 3,
    minimum_rate: float = 1,
    maximum_peak_mib: float = 128,
    deadline: float = 300,
) -> dict[str, object]:
    if any(
        type(value) is not int or value < 1
        for value in (documents, records, workers, samples)
    ):
        raise ValueError(
            "documents, records, workers, and samples must be positive integers"
        )
    if any(
        not math.isfinite(value) or value <= 0
        for value in (minimum_rate, maximum_peak_mib, deadline)
    ):
        raise ValueError("thresholds and deadline must be finite and positive")
    measurements: list[Sample] = []
    async with asyncio.timeout(deadline):
        for backend in ("async", "thread", "process"):
            measurements.extend(
                [
                    await measure(
                        backend, documents=documents, records=records, workers=workers
                    )
                    for _ in range(samples)
                ]
            )
    if len({row["digest"] for row in measurements}) != 1:
        raise AssertionError(
            "complete event fingerprints differ across backends or runs"
        )
    passed = all(
        row["records_per_second"] >= minimum_rate
        and row["caller_peak_traced_bytes"] <= maximum_peak_mib * 1024**2
        for row in measurements
    )
    return {
        "passed": passed,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "workers": workers,
        "documents": documents,
        "records_per_document": records,
        "minimum_records_per_second": minimum_rate,
        "maximum_caller_peak_mib": maximum_peak_mib,
        "memory_scope": "tracemalloc caller allocations only, not RSS or worker memory",
        "timing_note": (
            "tracemalloc is active in the caller, not process workers; "
            "cross-backend rates are not directly comparable"
        ),
        "latency_scope": (
            "per-document worker parsing, aggregation, codec and materialization; "
            "excludes queue delay"
        ),
        "measurements": measurements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=100)
    parser.add_argument("--records", type=int, default=100)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--minimum-rate", type=float, default=1)
    parser.add_argument("--maximum-peak-mib", type=float, default=128)
    parser.add_argument("--deadline", type=float, default=300)
    args = parser.parse_args()
    result = asyncio.run(
        run(
            documents=args.documents,
            records=args.records,
            workers=args.workers,
            samples=args.samples,
            minimum_rate=args.minimum_rate,
            maximum_peak_mib=args.maximum_peak_mib,
            deadline=args.deadline,
        )
    )
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
