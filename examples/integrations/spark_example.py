"""Run bounded Spark 4 jobs and assert exact local/worker evidence parity.

Exercises both allowlisted parsers (application-log and the fixed
mixed-content parser) in a single Spark batch, then prints a docs-safe
summary (counts, event types, and provenance only; never raw input).
"""

import json
import os

from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from examples.integrations.result_checks import verify_materialization
from examples.integrations.spark_batch import (
    SparkBatchParser,
    load_spark_session,
    make_job,
    make_mixed_content_job,
    parse_job,
    summarize_result,
)
from examples.integrations.spark_measure import measure_batch
from parsefabric.builtins import ApplicationLogParser
from parsefabric.models import ParseContext
from parsefabric.serialization import loads_result


async def main() -> None:
    session_type = load_spark_session()
    spark = (
        session_type.builder.master("local[2]")
        .appName("parsefabric-spark-example")
        .getOrCreate()
    )
    try:
        spark.sparkContext.setLogLevel("ERROR")
        print(f"Spark runtime: {spark.version}", flush=True)
        if not spark.version.startswith("4."):
            raise RuntimeError(f"Spark 4 is required, found {spark.version}")
        entries = [
            (
                "database timeout",
                ParseContext(
                    source_id="app-0.log", correlation_id="c-0", source_offset=20
                ),
            ),
            (
                "connection refused",
                ParseContext(
                    source_id="app-1.log", partition_id="p-1", source_offset=100
                ),
            ),
            (
                "retrying request",
                ParseContext(source_id="app-2.log", correlation_id="c-2"),
            ),
            (
                "service unavailable",
                ParseContext(source_id="app-3.log", partition_id="p-3"),
            ),
        ]
        mixed_context = ParseContext(source_id="mixed-0.log", correlation_id="c-mixed")
        jobs = [make_job(source, context) for source, context in entries]
        mixed_job_payload = make_mixed_content_job(MIXED_SOURCE, mixed_context)
        # One batch, two allowlisted parser types: application-log and mixed-content.
        actual = SparkBatchParser(spark).parse([*jobs, mixed_job_payload], partitions=2)
        expected = [
            await ApplicationLogParser().parse(source, context)
            for source, context in entries
        ] + [await mixed_parser().parse(MIXED_SOURCE, mixed_context)]
        if len(actual) != len(expected):
            raise AssertionError(
                f"Spark returned {len(actual)} records; expected {len(expected)}"
            )
        if actual != expected:
            raise AssertionError("Spark/local results or evidence differ")
        for result, (source, context) in zip(actual[:-1], entries, strict=True):
            verify_materialization(ApplicationLogParser(), source, context, result)
        verify_materialization(mixed_parser(), MIXED_SOURCE, mixed_context, actual[-1])
        if not all(
            item.events and item.events[0].evidence.source_id == context.source_id
            for item, (_, context) in zip(actual[: len(entries)], entries, strict=True)
        ):
            raise AssertionError("Spark evidence source identity differs")
        mixed_actual = actual[-1]
        if mixed_actual.parser_name != "mixed-content" or not mixed_actual.events:
            raise AssertionError("Spark mixed-content job did not route any events")
        mixed_summary = summarize_result(mixed_actual)
        print(
            "Spark mixed-content summary (counts/types/provenance only, no raw "
            f"input): {json.dumps(mixed_summary, sort_keys=True)}",
            flush=True,
        )
        if loads_result(parse_job(json.dumps(jobs[0]))) != expected[0]:
            raise AssertionError("versioned JSON result differs from local parsing")
        if loads_result(parse_job(json.dumps(mixed_job_payload))) != expected[-1]:
            raise AssertionError(
                "versioned JSON mixed-content result differs from local parsing"
            )
        incompatible = dict(jobs[0], schema_version="2")
        try:
            SparkBatchParser(spark).parse([incompatible])
        except ValueError as error:
            if "schema version" not in str(error):
                raise
        else:
            raise AssertionError("Spark accepted an incompatible job schema")
        unallowlisted = dict(mixed_job_payload, parser_name="unknown-parser")
        try:
            SparkBatchParser(spark).parse([unallowlisted])
        except ValueError as error:
            if "requested parser version" not in str(error):
                raise
        else:
            raise AssertionError("Spark accepted a non-allowlisted parser name")
        signals = (
            "database timeout",
            "connection refused",
            "retrying request",
            "service unavailable",
        )
        measurement_entries = [
            (
                signals[i % len(signals)],
                ParseContext(
                    source_id=f"sample-{i}.log",
                    correlation_id=f"sample-{i}",
                    partition_id=f"source-{i % 2}",
                    source_offset=i * 100,
                ),
            )
            for i in range(24)
        ]
        raw_minimum = os.getenv("PARSEFABRIC_SPARK_MIN_RECORDS_PER_SECOND", "")
        minimum = float(raw_minimum) if raw_minimum else None
        measure_batch(
            SparkBatchParser(spark),
            measurement_entries,
            minimum_records_per_second=minimum,
        )
        print(
            f"Spark 4 parity and evidence verified: {len(actual)} records "
            f"({len(entries)} application-log, 1 mixed-content); "
            "remote materialization verified",
            flush=True,
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
