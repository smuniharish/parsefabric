"""Submit and verify a finite mixed-content PyFlink DataStream.

Usage inside the optional Flink image:
    flink run -py /workspace/examples/integrations/flink_job.py \
        /results/output --records 32
    python /workspace/examples/integrations/flink_job.py \
        /results/output --verify --records 32
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from examples.integrations.flink_backend import (
    MAX_RECORDS,
    read_results,
    run_bounded_job,
)
from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from examples.integrations.result_checks import verify_materialization
from examples.integrations.sync_bridge import run_sync
from parsefabric.models import ParseContext, ParseResult

RECORDS = [
    (
        MIXED_SOURCE,
        ParseContext(
            source_id="mixed-0.txt",
            correlation_id="trace-1",
            partition_id="0",
            source_offset=42,
        ),
    ),
    (
        MIXED_SOURCE,
        ParseContext(
            source_id="mixed-1.txt",
            correlation_id="trace-2",
            partition_id="1",
            source_offset=128,
        ),
    ),
    (
        MIXED_SOURCE,
        ParseContext(
            source_id="mixed-2.txt",
            correlation_id="trace-3",
            partition_id="2",
            source_offset=256,
        ),
    ),
    (
        "quiet line\n" + MIXED_SOURCE,
        ParseContext(source_id="mixed-3.txt", partition_id="3", source_offset=0),
    ),
]


def representative_records(count: int) -> list[tuple[str, ParseContext]]:
    """Repeat mixed-format records without exceeding the bounded job contract."""
    if not 1 <= count <= MAX_RECORDS:
        raise ValueError(f"record count must be between 1 and {MAX_RECORDS}")
    return [RECORDS[index % len(RECORDS)] for index in range(count)]


def escaped_boundary_records() -> list[tuple[str, ParseContext]]:
    # Sized so the worker result stays below MAX_RESULT_BYTES while its escaped
    # envelope exceeds it, with margin on both sides.
    return [('"\\\n' * 2400, ParseContext(source_id="z" * 88))]


def verify_results(output: Path, records: list[tuple[str, ParseContext]]) -> int:
    actual: list[ParseResult] = read_results(output, len(records))
    if len(actual) != len(records):
        raise AssertionError(
            f"Flink returned {len(actual)} records; expected {len(records)}"
        )
    parser = mixed_parser()
    expected = [run_sync(parser.parse(source, context)) for source, context in records]
    if actual != expected:
        raise AssertionError("Flink result/evidence differs from local parser")
    for result, (source, context) in zip(actual, records, strict=True):
        verify_materialization(parser, source, context, result)
    try:
        run_bounded_job(records, output, parser_name="mixed-content")
    except ValueError as error:
        if "output directory must not exist" not in str(error):
            raise
    else:
        raise AssertionError("Flink accepted an existing finalized output directory")
    events = [event for result in actual for event in result.events]
    evidence = [event.evidence for event in events]
    summary = {
        "records": len(actual),
        "events": len(events),
        "event_types": dict(
            sorted(Counter(event.event_type for event in events).items())
        ),
        "provenance": {
            "source_ids": sorted(
                {item.source_id for item in evidence if item.source_id}
            ),
            "parser_names": sorted(
                {item.parser_name for item in evidence if item.parser_name}
            ),
            "pattern_names": sorted(
                {item.pattern_name for item in evidence if item.pattern_name}
            ),
            "partition_ids": sorted(
                {item.partition_id for item in evidence if item.partition_id}
            ),
            "correlation_ids": sorted(
                {item.correlation_id for item in evidence if item.correlation_id}
            ),
            "offset_range": [
                min(
                    (
                        item.start_offset
                        for item in evidence
                        if item.start_offset is not None
                    ),
                    default=None,
                ),
                max(
                    (
                        item.end_offset
                        for item in evidence
                        if item.end_offset is not None
                    ),
                    default=None,
                ),
            ],
        },
    }
    print("Flink mixed-content summary: " + json.dumps(summary, sort_keys=True))
    return len(actual)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--records", type=int, default=MAX_RECORDS)
    parser.add_argument("--escaped-boundary", action="store_true")
    args = parser.parse_args()
    records = (
        escaped_boundary_records()
        if args.escaped_boundary
        else representative_records(args.records)
    )
    if args.verify:
        verified = verify_results(args.output, records)
        print(
            f"Flink {verified} records: exact result and evidence parity; "
            "remote materialization verified"
        )
    else:
        run_bounded_job(records, args.output, parser_name="mixed-content")


if __name__ == "__main__":
    main()
