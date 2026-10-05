"""Opt-in bounded PyFlink DataStream job for allowlisted deterministic parsers.

Install ``apache-flink==2.3.0`` in the Flink runtime, not in ParseFabric's base
environment. Only versioned JSON records cross the DataStream boundary.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from importlib import import_module
from pathlib import Path

from examples.integrations.json_contract import decode_json as _decode
from examples.integrations.mixed_job import mixed_parser
from examples.integrations.sync_bridge import run_sync
from parsefabric.builtins import ApplicationLogParser
from parsefabric.models import ParseContext, ParseResult
from parsefabric.serialization import dumps_result, loads_result

FLINK_VERSION = "2.3.0"
MAX_RECORDS = 32
MAX_SOURCE_BYTES = 16_384
MAX_JOB_BYTES = MAX_SOURCE_BYTES + 4096
MAX_RESULT_BYTES = 1_048_576
# The envelope escapes the result JSON again; allow up to two bytes per byte.
MAX_OUTPUT_ROW_BYTES = 2 * MAX_RESULT_BYTES + 64
MAX_OUTPUT_BYTES = MAX_RECORDS * MAX_OUTPUT_ROW_BYTES
_CONTEXT_FIELDS = frozenset(
    ("source_id", "correlation_id", "partition_id", "source_offset")
)
_JOB_FIELDS = frozenset(
    ("schema_version", "parser_name", "parser_version", "index", "source", "context")
)
_PARSERS = {
    "application-log": ApplicationLogParser,
    "mixed-content": mixed_parser,
}


def _validate_job(job: object) -> tuple[int, str, ParseContext, str]:
    if not isinstance(job, dict) or set(job) != _JOB_FIELDS:
        raise ValueError("invalid Flink job fields")
    if (
        job["schema_version"] != "1"
        or not isinstance(job["parser_name"], str)
        or job["parser_name"] not in _PARSERS
        or job["parser_version"] != "1"
    ):
        raise ValueError("unsupported parser or job schema version")
    index = job["index"]
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not 0 <= index < MAX_RECORDS
    ):
        raise ValueError("invalid record index")
    source = job["source"]
    if not isinstance(source, str) or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("source must be UTF-8 text of at most 16 KiB")
    context = job["context"]
    if not isinstance(context, dict) or set(context) != _CONTEXT_FIELDS:
        raise ValueError("invalid context fields")
    return index, source, ParseContext(**context), job["parser_name"]


def encode_jobs(
    records: list[tuple[str, ParseContext]], *, parser_name: str = "application-log"
) -> list[str]:
    """Construct a finite, indexed, allowlisted stream without pickled callables."""
    if not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError(f"bounded Flink stream requires 1..{MAX_RECORDS} records")
    payloads: list[str] = []
    for index, item in enumerate(records):
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[1], ParseContext)
        ):
            raise ValueError("each record must contain source and ParseContext")
        job = {
            "schema_version": "1",
            "parser_name": parser_name,
            "parser_version": "1",
            "index": index,
            "source": item[0],
            "context": asdict(item[1]),
        }
        _validate_job(job)
        payload = json.dumps(job, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > MAX_JOB_BYTES:
            raise ValueError("oversized Flink job")
        payloads.append(payload)
    return payloads


def parse_record(payload: str) -> str:
    """Execute on a Flink Python worker; reject unrecognized job contracts."""
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_JOB_BYTES:
        raise ValueError("oversized Flink job")
    job = _decode(payload)
    index, source, context, parser_name = _validate_job(job)
    result = dumps_result(run_sync(_PARSERS[parser_name]().parse(source, context)))
    if len(result.encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValueError("oversized Flink result")
    return json.dumps({"index": index, "result": result}, ensure_ascii=False)


def read_results(directory: Path, count: int) -> list[ParseResult]:
    """Read finalized bounded FileSink parts, rejecting missing/duplicate output."""
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or not 1 <= count <= MAX_RECORDS
    ):
        raise ValueError("invalid result count")
    results: dict[int, ParseResult] = {}
    total = 0
    parts = sorted(directory.rglob("part-*"))
    if not parts:
        raise ValueError("Flink did not finalize any output parts")
    for part in parts:
        if not part.is_file():
            raise ValueError("Flink output part is not a file")
        with part.open("rb") as stream:
            while line := stream.readline(MAX_OUTPUT_ROW_BYTES + 1):
                total += len(line)
                if total > MAX_OUTPUT_BYTES or len(line) > MAX_OUTPUT_ROW_BYTES:
                    raise ValueError("Flink output exceeds bounded result size")
                row = _decode(line.decode("utf-8"))
                if not isinstance(row, dict) or set(row) != {"index", "result"}:
                    raise ValueError("invalid Flink output row")
                index, payload = row["index"], row["result"]
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or not 0 <= index < count
                    or index in results
                    or not isinstance(payload, str)
                    or len(payload.encode("utf-8")) > MAX_RESULT_BYTES
                ):
                    raise ValueError("invalid or duplicate Flink result")
                results[index] = loads_result(payload)
    if len(results) != count:
        raise ValueError("Flink output is missing records")
    return [results[index] for index in range(count)]


def run_bounded_job(
    records: list[tuple[str, ParseContext]],
    output: Path,
    *,
    parser_name: str = "application-log",
) -> None:
    """Submit a finite DataStream and wait for its FileSink to finalize.

    Call inside a PyFlink-equipped Flink cluster; no Flink import at module load.
    """
    jobs = encode_jobs(records, parser_name=parser_name)
    if output.exists():
        raise ValueError("output directory must not exist before submitting")
    try:
        common = import_module("pyflink.common")
        datastream = import_module("pyflink.datastream")
        file_system = import_module("pyflink.datastream.connectors.file_system")
    except ModuleNotFoundError as error:
        if error.name == "pyflink" or (
            error.name is not None and error.name.startswith("pyflink.")
        ):
            raise RuntimeError(
                "PyFlink is optional; install apache-flink==2.3.0 in the "
                "Flink runtime (see examples/integrations/README.md)"
            ) from error
        raise

    env = datastream.StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(2)
    sink = file_system.FileSink.for_row_format(
        str(output), common.Encoder.simple_string_encoder()
    ).build()
    env.from_collection(jobs, type_info=common.Types.STRING()).map(
        parse_record, output_type=common.Types.STRING()
    ).sink_to(sink)
    env.execute(f"parsefabric-bounded-{parser_name}-v1")
