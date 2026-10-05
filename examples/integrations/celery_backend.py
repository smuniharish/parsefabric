"""Run allowlisted application-log and mixed-content jobs on a Celery worker.

Run with the compose file under examples/integrations/. Celery and Redis are
installed only for this integration example, never by the base package.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import platform
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict
from typing import Any, TypedDict, TypeVar, cast, overload

from celery import Celery
from celery.exceptions import TimeoutError as CeleryTimeoutError

from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from examples.integrations.sync_bridge import run_sync
from parsefabric.builtins import ApplicationLogParser
from parsefabric.execution import ExecutionBackend
from parsefabric.models import ParseContext, ParseResult
from parsefabric.observability import LifecycleEvent, ObservabilitySink
from parsefabric.serialization import dumps_result, loads_result

T = TypeVar("T")
MAX_SOURCE_BYTES = 1_048_576
TASK_NAME = "parsefabric.examples.parse_application_log.v1"
APPLICATION_LOG_PARSER = ("application-log", "1")
MIXED_CONTENT_PARSER = ("mixed-content", "1")
_JOB_FIELDS = frozenset(
    ("schema_version", "parser_name", "parser_version", "source", "context")
)
EXPECTED_MIXED_EVENT_TYPES = {
    "code": 1,
    "error": 1,
    "fence": 2,
    "json_record": 1,
    "metric": 1,
    "other": 1,
    "timeout": 1,
}
EXPECTED_MIXED_PARSER_PROVENANCE = {
    "application-log": 2,
    "json": 1,
    "metrics": 1,
    "mixed-content": 4,
}
EXPECTED_MIXED_PATTERN_PROVENANCE = {
    "code_fence": 3,
    "error": 1,
    "json-line": 1,
    "metric": 1,
    "other": 1,
    "timeout": 1,
}


class _MixedProvenanceSummary(TypedDict):
    parser_names: dict[
        str,
        int,
    ]
    pattern_names: dict[
        str,
        int,
    ]


class _MixedResultSummary(TypedDict):
    result_matches_local: bool
    evidence_matches_local: bool
    event_count: int
    event_types: dict[str, int]
    provenance: _MixedProvenanceSummary


celery_app = Celery(
    "parsefabric_example",
    broker=os.environ.get("PARSEFABRIC_CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.environ.get("PARSEFABRIC_CELERY_RESULT_URL", "redis://redis:6379/1"),
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_accept_content=["json"],
    task_publish_retry=False,
    task_acks_late=False,
    result_expires=3600,
    worker_prefetch_multiplier=1,
)


def parse_application_log(
    source: str, context: ParseContext | None = None
) -> ParseResult:
    """Parse application logs using the fixed worker allowlist."""
    return run_sync(ApplicationLogParser().parse(source, context))


def parse_mixed_content(
    source: str, context: ParseContext | None = None
) -> ParseResult:
    """Parse the shared, deterministic mixed-content fixture."""
    return run_sync(mixed_parser().parse(source, context))


def _validated_job(job: object) -> tuple[str, ParseContext]:
    if not isinstance(job, dict) or set(job) != _JOB_FIELDS:
        raise ValueError("job must contain exactly the version-1 job fields")
    if job.get("schema_version") != "1":
        raise ValueError("unsupported job schema version")
    parser_identity = (job.get("parser_name"), job.get("parser_version"))
    if parser_identity not in (APPLICATION_LOG_PARSER, MIXED_CONTENT_PARSER):
        raise ValueError("worker does not have the requested parser version")
    source = job.get("source")
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("source must be text of at most 1 MiB UTF-8")
    raw_context = job.get("context")
    if not isinstance(raw_context, dict):
        raise ValueError("job context must be an object")
    return source, ParseContext(**raw_context)


def _validated_minimum_rate(value: str | None) -> float | None:
    if value is None:
        return None
    minimum = float(value)
    if not math.isfinite(minimum) or minimum <= 0:
        raise ValueError(
            "PARSEFABRIC_MIN_RECORDS_PER_SECOND must be finite and positive"
        )
    return minimum


def _validated_count(name: str, default: int) -> int:
    count = int(os.environ.get(name, str(default)))
    if count < 1:
        raise ValueError(f"{name} must be positive")
    return count


def _check_minimum_rate(rate: float, minimum: float | None) -> None:
    if minimum is not None and rate < minimum:
        raise RuntimeError(
            f"Celery throughput {rate:.2f} below {minimum:.2f} records/s"
        )


@celery_app.task(name=TASK_NAME)
def parse_job(job: dict[str, object]) -> str:
    """Worker-side, version-checked JSON envelope; never deserialize Python code."""
    source, context = _validated_job(job)
    parser_name = job["parser_name"]
    if parser_name == "application-log":
        result = parse_application_log(source, context)
    elif parser_name == "mixed-content":
        result = parse_mixed_content(source, context)
    else:
        raise AssertionError("validated job has an unsupported parser")
    return dumps_result(result)


def _wait_for_result(task_id: str, timeout: float) -> object:
    # Celery's Redis result backend is thread-local; construct it in the
    # thread that waits instead of moving the submitting thread's backend.
    return celery_app.AsyncResult(task_id).get(timeout=timeout, propagate=True)


class CeleryExecutionBackend(ExecutionBackend):
    """Submit an allowlisted parsing callable to an externally managed worker."""

    def __init__(
        self, *, timeout: float = 30.0, sink: ObservabilitySink | None = None
    ) -> None:
        super().__init__(sink)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self._timeout = timeout
        self._closed = False

    @overload
    async def run[R](
        self,
        function: Callable[..., Coroutine[Any, Any, R] | Awaitable[R]],
        /,
        *args: object,
        **kwargs: object,
    ) -> R: ...

    @overload
    async def run[R](
        self,
        function: Callable[..., R],
        /,
        *args: object,
        **kwargs: object,
    ) -> R: ...

    async def run(
        self,
        function: Callable[..., Any],
        /,
        *args: object,
        **kwargs: object,
    ) -> Any:
        if self._closed:
            raise RuntimeError("execution backend is shut down")
        is_application_log = function is parse_application_log
        is_mixed_content = function is parse_mixed_content
        if (
            not (is_application_log or is_mixed_content)
            or kwargs
            or len(args) not in (1, 2)
        ):
            raise ValueError(
                "Celery example supports only parse_application_log or "
                "parse_mixed_content"
            )
        parser_name, parser_version = (
            APPLICATION_LOG_PARSER if is_application_log else MIXED_CONTENT_PARSER
        )
        source = args[0]
        context = args[1] if len(args) == 2 else ParseContext()
        if not isinstance(context, ParseContext):
            raise TypeError("context must be a ParseContext")
        job: dict[str, object] = {
            "schema_version": "1",
            "parser_name": parser_name,
            "parser_version": parser_version,
            "source": source,
            "context": asdict(context),
        }
        _validated_job(job)
        self._sink.emit(LifecycleEvent("ExecutionSubmitted"))
        future = None
        try:
            future = await asyncio.to_thread(
                parse_job.apply_async, kwargs={"job": job}, retry=False
            )
            self._sink.emit(LifecycleEvent("ExecutionStarted"))
            payload = await asyncio.to_thread(
                _wait_for_result, future.id, self._timeout
            )
            if not isinstance(payload, str):
                raise ValueError("worker returned a non-string parse result")
            result = loads_result(payload)
        except asyncio.CancelledError:
            if future is not None:
                await asyncio.to_thread(future.revoke, terminate=False)
            self._sink.emit(LifecycleEvent("ExecutionCancelled"))
            raise
        except CeleryTimeoutError as error:
            if future is not None:
                await asyncio.to_thread(future.revoke, terminate=False)
            self._sink.emit(
                LifecycleEvent(
                    "ExecutionFailed", attributes={"error_type": "TimeoutError"}
                )
            )
            raise TimeoutError(
                "Celery parsing job timed out; running work may continue"
            ) from error
        except Exception as error:
            self._sink.emit(
                LifecycleEvent(
                    "ExecutionFailed", attributes={"error_type": type(error).__name__}
                )
            )
            raise
        self._sink.emit(LifecycleEvent("ExecutionCompleted"))
        return cast(T, result)

    async def shutdown(self) -> None:
        self._closed = True


async def main() -> None:
    # Wait for worker registration, not merely for the Redis socket to open.
    deadline = time.monotonic() + 60
    while not await asyncio.to_thread(celery_app.control.ping, timeout=2):
        if time.monotonic() >= deadline:
            raise TimeoutError("Celery worker did not become ready")
        await asyncio.sleep(1)

    parser = ApplicationLogParser()
    expected = await parser.parse(
        "database timeout", ParseContext(source_id="application.log")
    )
    minimum = _validated_minimum_rate(
        os.environ.get("PARSEFABRIC_MIN_RECORDS_PER_SECOND")
    )
    records = _validated_count("PARSEFABRIC_CELERY_RECORDS", 100)
    samples = _validated_count("PARSEFABRIC_CELERY_SAMPLES", 3)
    mixed_context = ParseContext(
        source_id="mixed-fixture.txt",
        correlation_id="celery-mixed-check",
        partition_id="mixed-p0",
        source_offset=23,
    )
    expected_mixed: ParseResult = parse_mixed_content(MIXED_SOURCE, mixed_context)
    async with CeleryExecutionBackend() as backend:
        actual = await backend.run(
            parse_application_log,
            "database timeout",
            ParseContext(source_id="application.log"),
        )
        if actual != expected:
            raise AssertionError(
                "remote parser result differs from local parser result"
            )
        actual_mixed: ParseResult = await backend.run(
            parse_mixed_content,
            MIXED_SOURCE,
            mixed_context,
        )
        if [event.evidence for event in actual_mixed.events] != [
            event.evidence for event in expected_mixed.events
        ]:
            raise AssertionError(
                "remote mixed-content evidence differs from local parsing"
            )
        if actual_mixed != expected_mixed:
            raise AssertionError(
                "remote mixed-content result differs from local parsing"
            )
        mixed_summary = _mixed_result_summary(actual_mixed)
        if (
            mixed_summary["event_count"] != sum(EXPECTED_MIXED_EVENT_TYPES.values())
            or mixed_summary["event_types"] != EXPECTED_MIXED_EVENT_TYPES
            or mixed_summary["provenance"]["parser_names"]
            != EXPECTED_MIXED_PARSER_PROVENANCE
            or mixed_summary["provenance"]["pattern_names"]
            != EXPECTED_MIXED_PATTERN_PROVENANCE
        ):
            raise AssertionError("mixed-content result counts or provenance differ")
        expected_record = await parser.parse("database timeout")
        measurements = []
        for _ in range(samples):
            start = time.perf_counter()
            completed = 0
            async for result in backend.map(
                parse_application_log,
                ("database timeout" for _ in range(records)),
                max_in_flight=2,
            ):
                if result != expected_record:
                    raise AssertionError(
                        "bounded remote map disagrees with local parsing"
                    )
                completed += 1
            elapsed = time.perf_counter() - start
            if completed != records:
                raise AssertionError(f"expected {records} results, got {completed}")
            rate = completed / elapsed
            measurements.append({"seconds": elapsed, "records_per_second": rate})
            _check_minimum_rate(rate, minimum)
        print(
            json.dumps(
                {
                    "backend": "celery",
                    "python_version": platform.python_version(),
                    "records_per_sample": records,
                    "samples": measurements,
                    "minimum_records_per_second": minimum,
                    "mixed_content": mixed_summary,
                }
            )
        )
        try:
            await backend.run(parse_application_log, object())
        except ValueError as error:
            if "source" not in str(error):
                raise
        else:
            raise AssertionError("invalid job was accepted")
        incompatible = await asyncio.to_thread(
            parse_job.apply_async,
            kwargs={
                "job": {
                    "schema_version": "2",
                    "parser_name": "application-log",
                    "parser_version": "1",
                    "source": "database timeout",
                    "context": {},
                }
            },
            retry=False,
        )
        try:
            await asyncio.to_thread(_wait_for_result, incompatible.id, 30)
        except ValueError as error:
            if "schema version" not in str(error):
                raise
        else:
            raise AssertionError("worker accepted an incompatible job schema")
        incompatible_parser = await asyncio.to_thread(
            parse_job.apply_async,
            kwargs={
                "job": {
                    "schema_version": "1",
                    "parser_name": "mixed-content",
                    "parser_version": "2",
                    "source": MIXED_SOURCE,
                    "context": {},
                }
            },
            retry=False,
        )
        try:
            await asyncio.to_thread(_wait_for_result, incompatible_parser.id, 30)
        except ValueError as error:
            if "parser version" not in str(error):
                raise
        else:
            raise AssertionError("worker accepted an incompatible parser version")
    print("Celery worker produced matching application-log and mixed-content results")


def _mixed_result_summary(result: ParseResult) -> _MixedResultSummary:
    """Summarize event types and evidence provenance without exposing attributes."""
    event_types = Counter(event.event_type for event in result.events)
    parser_names = Counter(
        event.evidence.parser_name or "unknown" for event in result.events
    )
    pattern_names = Counter(
        event.evidence.pattern_name or "unknown" for event in result.events
    )
    return {
        "result_matches_local": True,
        "evidence_matches_local": True,
        "event_count": len(result.events),
        "event_types": dict(sorted(event_types.items())),
        "provenance": {
            "parser_names": dict(sorted(parser_names.items())),
            "pattern_names": dict(sorted(pattern_names.items())),
        },
    }


if __name__ == "__main__":
    asyncio.run(main())
