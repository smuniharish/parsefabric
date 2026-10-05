import json

import pytest

from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from examples.integrations.spark_batch import (
    MAX_RECORDS,
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


class FakeRDD:
    def __init__(self, items: list[tuple[int, str]]) -> None:
        self.items = items

    def mapPartitions(self, function: object) -> "FakeRDD":  # noqa: N802 - PySpark API name
        self.items = list(function(iter(self.items)))  # type: ignore[operator]
        return self

    def collect(self) -> list[tuple[int, str]]:
        return list(reversed(self.items))


class FakeContext:
    def __init__(self) -> None:
        self.partitions = 0
        self.submissions = 0

    def parallelize(self, items: list[tuple[int, str]], partitions: int) -> FakeRDD:
        self.submissions += 1
        self.partitions = partitions
        return FakeRDD(items)


class FakeSpark:
    version = "4.0.1"

    def __init__(self) -> None:
        self.sparkContext = FakeContext()


async def test_worker_json_round_trip_preserves_evidence() -> None:
    context = ParseContext(
        source_id="app.log", correlation_id="c-1", partition_id="p-1", source_offset=100
    )
    actual = loads_result(parse_job(json.dumps(make_job("database timeout", context))))
    assert actual == await ApplicationLogParser().parse("database timeout", context)
    assert actual.events[0].evidence.source_id == "app.log"
    assert actual.events[0].evidence.partition_id == "p-1"
    assert actual.events[0].evidence.start_offset == 100


async def test_batch_preserves_input_order_and_exact_local_parity() -> None:
    spark = FakeSpark()
    jobs = [
        make_job(f"database timeout {i}", ParseContext(source_id=f"{i}.log"))
        for i in range(4)
    ]
    result = SparkBatchParser(spark).parse(iter(jobs), partitions=2)
    assert result == [
        await ApplicationLogParser().parse(
            f"database timeout {i}", ParseContext(source_id=f"{i}.log")
        )
        for i in range(4)
    ]
    assert spark.sparkContext.partitions == 2
    assert spark.sparkContext.submissions == 1
    assert SparkBatchParser(spark).parse([]) == []
    assert spark.sparkContext.submissions == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "2", "schema version"),
        ("parser_name", "json", "parser version"),
        ("parser_version", "2", "parser version"),
        ("source", 123, "source"),
        ("source", "é" * 524_289, "source"),
        ("context", [], "context"),
        ("context", {"source_id": "foo"}, "context"),
        (
            "context",
            {
                "source_id": None,
                "correlation_id": None,
                "partition_id": None,
                "source_offset": -1,
            },
            "source_offset",
        ),
    ],
    ids=(
        "job-version",
        "parser-name",
        "parser-version",
        "non-text",
        "utf8-size",
        "context-type",
        "context-fields",
        "context-offset",
    ),
)
def test_worker_rejects_bad_contract(field: str, value: object, message: str) -> None:
    job = make_job("database timeout")
    job[field] = value
    with pytest.raises((ValueError, TypeError), match=message):
        parse_job(json.dumps(job, default=str))


def test_worker_rejects_invalid_json_and_unknown_fields() -> None:
    with pytest.raises(ValueError, match="invalid Spark job JSON"):
        parse_job("{")
    with pytest.raises(ValueError, match="JSON text"):
        parse_job(None)  # type: ignore[arg-type]
    job = make_job("text")
    job["callable"] = "builtins.eval"
    with pytest.raises(ValueError, match="exactly"):
        parse_job(json.dumps(job))


def test_driver_rejects_oversize_and_incompatible_before_spark_submission() -> None:
    spark = FakeSpark()
    parser = SparkBatchParser(spark)
    with pytest.raises(ValueError, match="records"):
        parser.parse(make_job("text") for _ in range(MAX_RECORDS + 1))
    with pytest.raises(ValueError, match="8 MiB"):
        parser.parse(make_job("x" * 500_000) for _ in range(17))
    with pytest.raises(ValueError, match="schema version"):
        parser.parse([dict(make_job("text"), schema_version="2")])
    with pytest.raises(ValueError, match="partitions"):
        parser.parse([make_job("text")], partitions=0)
    assert spark.sparkContext.submissions == 0


def test_driver_requires_spark_4_and_complete_unique_results() -> None:
    spark = FakeSpark()
    spark.version = "3.5.0"
    with pytest.raises(ValueError, match="Spark 4"):
        SparkBatchParser(spark)
    spark.version = "4.0.1"
    parser = SparkBatchParser(spark)

    class IncompleteRDD(FakeRDD):
        def collect(self) -> list[tuple[int, str]]:
            return [(0, self.items[0][1]), (0, self.items[0][1])]

    spark.sparkContext.parallelize = lambda items, partitions: IncompleteRDD(items)  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="missing or duplicate"):
        parser.parse([make_job("a"), make_job("b")])


def test_sample_reports_records_elapsed_and_rate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = [
        ("database timeout", ParseContext(source_id="one.log")),
        ("connection refused", ParseContext(source_id="two.log")),
    ]
    result = measure_batch(
        SparkBatchParser(FakeSpark()),
        entries,
        minimum_records_per_second=1,
        clock=iter((5.0, 6.0)).__next__,
    )
    assert result == (2, 1.0, 2.0)
    assert "2 records in 1.000 s (2.00 records/s" in capsys.readouterr().out


async def test_sample_rejects_wrong_count_and_mismatched_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = SparkBatchParser(FakeSpark())
    entries = [("database timeout", ParseContext(source_id="correct.log"))]
    monkeypatch.setattr(parser, "parse", lambda jobs, partitions: [])
    with pytest.raises(AssertionError, match="returned 0 records; expected 1"):
        measure_batch(parser, entries, clock=iter((1.0, 2.0)).__next__)
    wrong = await ApplicationLogParser().parse(
        "database timeout", ParseContext(source_id="wrong.log")
    )
    monkeypatch.setattr(parser, "parse", lambda jobs, partitions: [wrong])
    with pytest.raises(AssertionError, match="results or evidence differ"):
        measure_batch(parser, entries, clock=iter((1.0, 2.0)).__next__)


def test_sample_optional_rate_gate_and_invalid_threshold() -> None:
    parser = SparkBatchParser(FakeSpark())
    entries = [("database timeout", ParseContext(source_id="one.log"))]
    with pytest.raises(AssertionError, match="below configured minimum"):
        measure_batch(
            parser,
            entries,
            minimum_records_per_second=2,
            clock=iter((1.0, 2.0)).__next__,
        )
    for threshold in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="finite and positive"):
            measure_batch(parser, entries, minimum_records_per_second=threshold)
    with pytest.raises(ValueError, match="1 to 32 records"):
        measure_batch(parser, [])
    with pytest.raises(ValueError, match="1 to 32 records"):
        measure_batch(parser, entries * (MAX_RECORDS + 1))


def test_optional_pyspark_import_has_actionable_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> object:
        assert name == "pyspark.sql"
        raise ModuleNotFoundError("No module named 'pyspark'", name="pyspark")

    monkeypatch.setattr("examples.integrations.spark_batch.import_module", missing)
    with pytest.raises(ImportError, match=r"install pyspark>=4,<5"):
        load_spark_session()


async def test_worker_accepts_mixed_content_job_with_exact_local_parity() -> None:
    context = ParseContext(source_id="mixed.log", correlation_id="c-mixed")
    job = make_mixed_content_job(MIXED_SOURCE, context)
    assert job["parser_name"] == "mixed-content"
    assert job["parser_version"] == "1"
    actual = loads_result(parse_job(json.dumps(job)))
    expected = await mixed_parser().parse(MIXED_SOURCE, context)
    assert actual == expected
    assert actual.parser_name == "mixed-content"
    assert actual.parser_version == "1"
    assert len(actual.events) == len(expected.events) > 0


async def test_batch_runs_mixed_content_jobs_alongside_application_log_jobs() -> None:
    spark = FakeSpark()
    jobs = [
        make_job("database timeout", ParseContext(source_id="0.log")),
        make_mixed_content_job(MIXED_SOURCE, ParseContext(source_id="1.log")),
    ]
    actual = SparkBatchParser(spark).parse(jobs, partitions=2)
    assert actual == [
        await ApplicationLogParser().parse(
            "database timeout", ParseContext(source_id="0.log")
        ),
        await mixed_parser().parse(MIXED_SOURCE, ParseContext(source_id="1.log")),
    ]


def test_make_job_rejects_parser_outside_the_allowlist() -> None:
    with pytest.raises(ValueError, match="unknown allowlisted parser"):
        make_job("text", parser_name="json", parser_version="1")
    with pytest.raises(ValueError, match="unknown allowlisted parser"):
        make_job("text", parser_name="mixed-content", parser_version="2")


async def test_summarize_result_reports_counts_types_and_provenance_without_raw_source() -> (  # noqa: E501
    None
):
    context = ParseContext(source_id="mixed.log", correlation_id="c-mixed")
    result = await mixed_parser().parse(MIXED_SOURCE, context)
    summary = summarize_result(result)
    assert summary["parser_name"] == "mixed-content"
    assert summary["parser_version"] == "1"
    assert summary["event_count"] == len(result.events) > 0
    assert sum(summary["event_type_counts"].values()) == summary["event_count"]
    assert "mixed.log" in summary["provenance_source_ids"]
    assert summary["provenance_parser_names"]
    assert summary["provenance_pattern_names"]
    serialized = json.dumps(summary)
    assert MIXED_SOURCE not in serialized
    assert "database timeout" not in serialized
    assert "print(" not in serialized


@pytest.mark.parametrize("field", ["schema_version", "source", "context"])
def test_worker_rejects_duplicate_json_fields(field: str) -> None:
    payload = json.dumps(make_job("database timeout"))
    payload = (
        payload[:-1] + f', "{field}": ' + json.dumps(make_job("quiet")[field]) + "}"
    )
    with pytest.raises(ValueError, match="duplicate JSON field"):
        parse_job(payload)


@pytest.mark.parametrize("field", ["parser_name", "parser_version"])
def test_worker_rejects_nonstring_parser_identity(field: str) -> None:
    job = make_job("database timeout")
    job[field] = []
    with pytest.raises(ValueError, match="parser version"):
        parse_job(json.dumps(job))


@pytest.mark.parametrize("index", [False, 0.0])
def test_driver_rejects_noninteger_result_indices(index: object) -> None:
    spark = FakeSpark()

    class InvalidIndexRDD(FakeRDD):
        def collect(self) -> list[tuple[int, str]]:
            return [(index, self.items[0][1])]  # type: ignore[list-item]

    spark.sparkContext.parallelize = lambda items, partitions: InvalidIndexRDD(items)  # type: ignore[method-assign]
    with pytest.raises(ValueError, match=r"invalid.*result"):
        SparkBatchParser(spark).parse([make_job("database timeout")])
