import io
import json
from pathlib import Path

import pytest

from examples.integrations import flink_backend, flink_job
from examples.integrations.flink_backend import (
    MAX_RECORDS,
    _validate_job,
    encode_jobs,
    parse_record,
    read_results,
)
from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from parsefabric.builtins import ApplicationLogParser
from parsefabric.models import ParseContext
from parsefabric.serialization import dumps_result


def _record() -> tuple[str, ParseContext]:
    return (
        "üñícode timeout",
        ParseContext(
            source_id="app.log",
            correlation_id="trace-7",
            partition_id="part-1",
            source_offset=27,
        ),
    )


async def test_worker_round_trip_preserves_exact_result_and_evidence() -> None:
    record = _record()
    payloads = encode_jobs([record, ("quiet", ParseContext())])
    decoded = [json.loads(parse_record(payload)) for payload in payloads]
    assert [row["index"] for row in decoded] == [0, 1]
    expected = await ApplicationLogParser().parse(*record)
    assert json.loads(decoded[0]["result"]) == json.loads(dumps_result(expected))
    assert json.loads(decoded[1]["result"])["events"] == []
    evidence = json.loads(decoded[0]["result"])["events"][0]["evidence"]
    assert evidence["source_id"] == "app.log"
    assert evidence["correlation_id"] == "trace-7"
    assert evidence["partition_id"] == "part-1"
    assert evidence["start_offset"] >= 27


async def test_mixed_worker_round_trip_preserves_all_results_and_provenance() -> None:
    records = flink_job.representative_records(4)
    payloads = encode_jobs(records, parser_name="mixed-content")
    assert all(json.loads(job)["parser_name"] == "mixed-content" for job in payloads)
    decoded = [json.loads(parse_record(job)) for job in payloads]
    assert [row["index"] for row in decoded] == list(range(4))
    expected = [await mixed_parser().parse(*record) for record in records]
    assert [json.loads(row["result"]) for row in decoded] == [
        json.loads(dumps_result(result)) for result in expected
    ]
    assert {event.event_type for result in expected for event in result.events} >= {
        "timeout",
        "json_record",
        "metric",
        "code",
        "other",
    }
    assert records[0][0] == MIXED_SOURCE


def test_mixed_job_contract_rejects_custom_parsers_and_unsafe_json() -> None:
    record = flink_job.RECORDS[0]
    with pytest.raises(ValueError, match="unsupported parser"):
        encode_jobs([record], parser_name="untrusted-parser")
    valid = encode_jobs([record], parser_name="mixed-content")[0]
    for changed in (
        valid.replace('"parser_version": "1"', '"parser_version": "2"'),
        valid.replace('"parser_name": "mixed-content"', '"parser_name": "arbitrary"'),
        valid.replace('"schema_version": "1"', '"schema_version": "2"'),
        valid.replace('"index": 0', '"index": NaN'),
        valid.replace('"index": 0', '"index": 0, "index": 0'),
    ):
        with pytest.raises(ValueError):
            parse_record(changed)


@pytest.mark.parametrize(
    "records",
    [
        [],
        [_record()] * (MAX_RECORDS + 1),
        [(42, ParseContext())],
        [("a" * 16_385, ParseContext())],
        [("valid", object())],
    ],
)
def test_client_rejects_unbounded_or_invalid_records(records: list[object]) -> None:
    with pytest.raises(ValueError):
        encode_jobs(records)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("parser_name", "arbitrary-code"),
        ("parser_version", "2"),
        ("index", True),
        ("index", MAX_RECORDS),
        ("source", "a" * 16_385),
        ("context", {"source_id": "x"}),
    ],
)
def test_worker_rejects_incompatible_contract(field: str, value: object) -> None:
    job = json.loads(encode_jobs([_record()])[0])
    job[field] = value
    with pytest.raises(ValueError):
        _validate_job(job)
    with pytest.raises(ValueError):
        parse_record(json.dumps(job))


@pytest.mark.parametrize(
    "payload",
    [
        '{"index":0,"source":NaN}',
        '{"index":0,"index":1}',
        "[]",
        "{" + "x" * 20_500 + "}",
    ],
)
def test_worker_rejects_malformed_or_nonfinite_json(payload: str) -> None:
    with pytest.raises(ValueError):
        parse_record(payload)


async def test_reader_orders_parts_and_rejects_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        parse_record(item)
        for item in encode_jobs([_record(), ("quiet", ParseContext())])
    ]
    part_a, part_b = Path("part-a"), Path("part-b")
    blobs = {
        part_a: (rows[1] + "\n").encode(),
        part_b: (rows[0] + "\n").encode(),
    }
    monkeypatch.setattr(Path, "rglob", lambda self, pattern: [part_a, part_b])
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "open", lambda self, mode: io.BytesIO(blobs[self]))
    actual = read_results(Path("output"), 2)
    assert actual == [
        await ApplicationLogParser().parse(*_record()),
        await ApplicationLogParser().parse("quiet", ParseContext()),
    ]
    blobs[part_b] = blobs[part_a]
    with pytest.raises(ValueError, match="duplicate"):
        read_results(Path("output"), 2)


def test_reader_rejects_missing_and_oversized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part = Path("part-a")
    monkeypatch.setattr(Path, "rglob", lambda self, pattern: [part])
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "open", lambda self, mode: io.BytesIO(b""))
    with pytest.raises(ValueError, match="missing"):
        read_results(Path("output"), 1)
    monkeypatch.setattr(
        Path,
        "open",
        lambda self, mode: io.BytesIO(b"x" * (flink_backend.MAX_OUTPUT_ROW_BYTES + 1)),
    )
    with pytest.raises(ValueError, match="exceeds"):
        read_results(Path("output"), 1)


@pytest.mark.parametrize("count", [0, MAX_RECORDS + 1])
def test_representative_sample_rejects_out_of_bounds(count: int) -> None:
    with pytest.raises(ValueError, match="record count"):
        flink_job.representative_records(count)


def test_representative_sample_preserves_mixed_input() -> None:
    records = flink_job.representative_records(MAX_RECORDS)
    assert len(records) == MAX_RECORDS
    assert records[: len(flink_job.RECORDS)] == flink_job.RECORDS
    assert records[len(flink_job.RECORDS) :] == flink_job.RECORDS * (
        MAX_RECORDS // len(flink_job.RECORDS) - 1
    )


async def test_verification_fails_on_wrong_count_or_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    records = flink_job.representative_records(2)
    expected = [await mixed_parser().parse(*record) for record in records]
    monkeypatch.setattr(flink_job, "read_results", lambda path, count: expected[:1])
    with pytest.raises(AssertionError, match="returned 1 records; expected 2"):
        flink_job.verify_results(Path("output"), records)

    wrong_context = ParseContext(source_id="wrong.log")
    wrong = await mixed_parser().parse(records[0][0], wrong_context)
    monkeypatch.setattr(
        flink_job, "read_results", lambda path, count: [wrong, expected[1]]
    )
    with pytest.raises(AssertionError, match="result/evidence differs"):
        flink_job.verify_results(Path("output"), records)

    monkeypatch.setattr(flink_job, "read_results", lambda path, count: expected)

    def existing_output(*args: object, **kwargs: object) -> None:
        raise ValueError("output directory must not exist before submitting")

    monkeypatch.setattr(flink_job, "run_bounded_job", existing_output)
    assert flink_job.verify_results(Path("output"), records) == 2
    summary = json.loads(capsys.readouterr().out.split("summary: ")[-1])
    assert summary["records"] == 2
    assert summary["events"] == sum(len(result.events) for result in expected)
    assert summary["event_types"]
    assert summary["provenance"]["source_ids"] == ["mixed-0.txt", "mixed-1.txt"]
    assert summary["provenance"]["offset_range"][0] >= 42
    assert MIXED_SOURCE not in json.dumps(summary)


async def test_verifier_rejects_accidental_output_reuse_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = flink_job.representative_records(1)
    expected = [await mixed_parser().parse(*record) for record in records]
    monkeypatch.setattr(flink_job, "read_results", lambda path, count: expected)
    monkeypatch.setattr(flink_job, "run_bounded_job", lambda *args, **kwargs: None)
    with pytest.raises(AssertionError, match="existing finalized output"):
        flink_job.verify_results(Path("output"), records)


def test_missing_optional_pyflink_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(name: str) -> None:
        raise ModuleNotFoundError("No module named 'pyflink'", name="pyflink")

    monkeypatch.setattr(flink_backend, "import_module", unavailable)
    with pytest.raises(RuntimeError, match=r"install apache-flink==2\.3\.0"):
        flink_backend.run_bounded_job([_record()], Path("unused-flink-output"))


def test_unrelated_missing_dependency_is_not_misreported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(name: str) -> None:
        raise ModuleNotFoundError("missing unrelated module", name="unrelated")

    monkeypatch.setattr(flink_backend, "import_module", unavailable)
    with pytest.raises(ModuleNotFoundError, match="unrelated"):
        flink_backend.run_bounded_job([_record()], Path("unused-flink-output"))


def test_driver_rejects_envelope_that_worker_would_reject() -> None:
    records: list[tuple[str, ParseContext]] = [
        ("x" * 16_384, ParseContext(source_id="y" * 4096)),
    ]
    with pytest.raises(ValueError, match="oversized Flink job"):
        encode_jobs(records, parser_name="mixed-content")


def test_reader_accepts_escaped_worker_result_within_payload_limit(
    tmp_path: Path,
) -> None:
    (record,) = flink_job.escaped_boundary_records()
    row = parse_record(encode_jobs([record], parser_name="mixed-content")[0])
    assert len(json.loads(row)["result"].encode()) <= flink_backend.MAX_RESULT_BYTES
    assert len(row.encode()) > flink_backend.MAX_RESULT_BYTES + 4096
    (tmp_path / "part-0").write_text(row + "\n", encoding="utf-8")
    assert len(read_results(tmp_path, 1)[0].events) == 2400


@pytest.mark.parametrize("count", [True, 1.0])
def test_reader_rejects_noninteger_counts(tmp_path: Path, count: object) -> None:
    row = parse_record(encode_jobs([_record()])[0])
    (tmp_path / "part-0").write_text(row + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid result count"):
        read_results(tmp_path, count)  # type: ignore[arg-type]


def test_reader_bounds_each_read_before_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sizes: list[int] = []

    class RecordingStream(io.BytesIO):
        def readline(self, size: int | None = -1, /) -> bytes:
            assert size is not None
            sizes.append(size)
            assert size == flink_backend.MAX_OUTPUT_ROW_BYTES + 1
            return super().readline(size)

    part = Path("part-0")
    monkeypatch.setattr(Path, "rglob", lambda self, pattern: [part])
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(
        Path,
        "open",
        lambda self, mode: RecordingStream(
            b"x" * (flink_backend.MAX_OUTPUT_ROW_BYTES + 128)
        ),
    )
    with pytest.raises(ValueError, match="exceeds bounded result size"):
        read_results(Path("output"), 1)
    assert len(sizes) == 1
