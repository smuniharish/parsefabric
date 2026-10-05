"""Opt-in Spark 4 batch jobs for allowlisted, unchanged parsers.

The driver submits a bounded, versioned JSON job contract naming one of a
fixed set of allowlisted parsers. Spark workers instantiate that exact
parser and return versioned ParseResult JSON; no Python callables or
caller-defined parser configuration cross the job boundary.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from importlib import import_module
from typing import Any, Protocol, TypedDict

from examples.integrations.json_contract import decode_json
from examples.integrations.mixed_job import mixed_parser
from examples.integrations.sync_bridge import run_sync
from parsefabric.builtins import ApplicationLogParser
from parsefabric.models import ParseContext, ParseResult
from parsefabric.parser import Parser
from parsefabric.serialization import dumps_result, loads_result


class SparkSessionLike(Protocol):
    """Only the Spark session attributes required by this bounded adapter."""

    version: str
    sparkContext: Any  # noqa: N815 - PySpark attribute name


def load_spark_session() -> Any:
    """Import optional PySpark only for callers creating a Spark session."""
    try:
        return import_module("pyspark.sql").SparkSession
    except ModuleNotFoundError as error:
        if error.name != "pyspark":
            raise
        raise ImportError(
            "Spark integration requires PySpark 4; install pyspark>=4,<5 "
            "in the environment running the Spark driver and workers"
        ) from error


MAX_RECORDS = 32
MAX_SOURCE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 8_388_608
_CONTEXT_KEYS = frozenset(
    ("source_id", "correlation_id", "partition_id", "source_offset")
)
_JOB_KEYS = frozenset(
    ("schema_version", "parser_name", "parser_version", "source", "context")
)

# Fixed allowlist of (parser_name, parser_version) -> zero-argument factory.
# Every factory returns the same deterministic parser configuration on the
# driver and on every worker; callers cannot substitute or configure it.
_PARSER_ALLOWLIST: dict[tuple[str, str], Any] = {
    ("application-log", "1"): ApplicationLogParser,
    ("mixed-content", "1"): mixed_parser,
}


def make_job(
    source: str,
    context: ParseContext | None = None,
    *,
    parser_name: str = "application-log",
    parser_version: str = "1",
) -> dict[str, object]:
    """Construct a version-1 parsing job for one allowlisted parser."""
    if (parser_name, parser_version) not in _PARSER_ALLOWLIST:
        raise ValueError(
            f"unknown allowlisted parser: {parser_name} version {parser_version}"
        )
    return {
        "schema_version": "1",
        "parser_name": parser_name,
        "parser_version": parser_version,
        "source": source,
        "context": asdict(context or ParseContext()),
    }


def make_mixed_content_job(
    source: str, context: ParseContext | None = None
) -> dict[str, object]:
    """Construct a version-1 job for the fixed, allowlisted mixed-content parser."""
    return make_job(source, context, parser_name="mixed-content", parser_version="1")


def _validated_job(job: object) -> tuple[str, ParseContext, Parser]:
    if not isinstance(job, dict) or set(job) != _JOB_KEYS:
        raise ValueError("job must contain exactly the version-1 job fields")
    if job["schema_version"] != "1":
        raise ValueError("unsupported job schema version")
    if not isinstance(job["parser_name"], str) or not isinstance(
        job["parser_version"], str
    ):
        raise ValueError("worker does not have the requested parser version")
    factory = _PARSER_ALLOWLIST.get((job["parser_name"], job["parser_version"]))
    if factory is None:
        raise ValueError("worker does not have the requested parser version")
    source = job["source"]
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("source must be text of at most 1 MiB UTF-8")
    raw_context = job["context"]
    if not isinstance(raw_context, dict) or set(raw_context) != _CONTEXT_KEYS:
        raise ValueError("job context must contain exactly the ParseContext fields")
    return source, ParseContext(**raw_context), factory()


def parse_job(payload: str) -> str:
    """Worker-side JSON boundary; reject unknown job and parser versions."""
    if not isinstance(payload, str):
        raise ValueError("Spark job payload must be JSON text")
    try:
        job = decode_json(payload)
    except json.JSONDecodeError as error:
        raise ValueError("invalid Spark job JSON") from error
    source, context, parser = _validated_job(job)
    return dumps_result(run_sync(parser.parse(source, context)))


def _parse_partition(rows: Iterator[tuple[int, str]]) -> Iterator[tuple[int, str]]:
    for index, payload in rows:
        yield index, parse_job(payload)


class SparkBatchParser:
    """Run a finite batch on a caller-managed Spark 4 session.

    The driver validates all inputs before submission, caps records and total
    payload, then collects at most MAX_RECORDS results in original order.
    Caller owns the SparkSession lifecycle and cluster configuration.
    """

    def __init__(self, spark: SparkSessionLike) -> None:
        if not spark.version.startswith("4."):
            raise ValueError("Spark 4 is required")
        self._spark = spark

    def parse(
        self, jobs: Iterable[dict[str, object]], *, partitions: int = 2
    ) -> list[ParseResult]:
        if (
            not isinstance(partitions, int)
            or isinstance(partitions, bool)
            or not 1 <= partitions <= 8
        ):
            raise ValueError("partitions must be an integer between 1 and 8")
        batch: list[tuple[int, str]] = []
        total_bytes = 0
        for index, job in enumerate(jobs):
            if index >= MAX_RECORDS:
                raise ValueError(f"batch exceeds {MAX_RECORDS} records")
            _validated_job(job)
            payload = json.dumps(job, ensure_ascii=False, allow_nan=False)
            total_bytes += len(payload.encode("utf-8"))
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("batch exceeds 8 MiB")
            batch.append((index, payload))
        if not batch:
            return []
        rows = (
            self._spark.sparkContext.parallelize(batch, min(partitions, len(batch)))
            .mapPartitions(_parse_partition)
            .collect()
        )
        if any(
            not isinstance(row, (tuple, list))
            or len(row) != 2
            or not isinstance(row[0], int)
            or isinstance(row[0], bool)
            or not isinstance(row[1], str)
            for row in rows
        ):
            raise ValueError("Spark returned invalid result rows")
        if len(rows) != len(batch) or sorted(index for index, _ in rows) != list(
            range(len(batch))
        ):
            raise ValueError("Spark returned missing or duplicate results")
        return [loads_result(payload) for _, payload in sorted(rows)]


class ResultSummary(TypedDict):
    """Doc-safe, JSON-serializable summary of one ParseResult."""

    parser_name: str | None
    parser_version: str | None
    event_count: int
    event_type_counts: dict[str, int]
    warning_count: int
    error_count: int
    provenance_parser_names: list[str]
    provenance_pattern_names: list[str]
    provenance_source_ids: list[str]


def summarize_result(result: ParseResult) -> ResultSummary:
    """Doc-safe counts, event types, and provenance; never raw parsed text.

    Suitable for printing or recording in documentation: reports only
    aggregate counts and identity metadata (parser, pattern, and source
    identifiers), never event attributes or the original source text.
    """
    type_counts: dict[str, int] = {}
    parser_names: set[str] = set()
    pattern_names: set[str] = set()
    source_ids: set[str] = set()
    for event in result.events:
        type_counts[event.event_type] = type_counts.get(event.event_type, 0) + 1
        if event.evidence.parser_name:
            parser_names.add(event.evidence.parser_name)
        if event.evidence.pattern_name:
            pattern_names.add(event.evidence.pattern_name)
        if event.evidence.source_id:
            source_ids.add(event.evidence.source_id)
    return {
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "event_count": len(result.events),
        "event_type_counts": dict(sorted(type_counts.items())),
        "warning_count": len(result.warnings),
        "error_count": len(result.errors),
        "provenance_parser_names": sorted(parser_names),
        "provenance_pattern_names": sorted(pattern_names),
        "provenance_source_ids": sorted(source_ids),
    }
