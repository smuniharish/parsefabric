import asyncio
import json
import threading

import pytest
from celery.exceptions import TimeoutError as CeleryTimeoutError

from examples.integrations.celery_backend import (
    APPLICATION_LOG_PARSER,
    EXPECTED_MIXED_EVENT_TYPES,
    EXPECTED_MIXED_PARSER_PROVENANCE,
    EXPECTED_MIXED_PATTERN_PROVENANCE,
    MIXED_CONTENT_PARSER,
    CeleryExecutionBackend,
    _check_minimum_rate,
    _mixed_result_summary,
    _validated_count,
    _validated_job,
    _validated_minimum_rate,
    celery_app,
    main,
    parse_application_log,
    parse_job,
    parse_mixed_content,
)
from examples.integrations.mixed_job import MIXED_SOURCE
from parsefabric.models import ParseContext
from parsefabric.observability import LifecycleEvent, ObservabilitySink
from parsefabric.serialization import dumps_result, loads_result


def test_remote_throughput_gate_accepts_and_rejects_thresholds() -> None:
    _check_minimum_rate(300.0, 300.0)
    _check_minimum_rate(300.0, None)
    with pytest.raises(RuntimeError, match="below"):
        _check_minimum_rate(299.0, 300.0)
    assert _validated_minimum_rate(None) is None
    assert _validated_minimum_rate("300") == 300.0
    with pytest.raises(ValueError, match="finite and positive"):
        _validated_minimum_rate("nan")


def test_remote_throughput_counts_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSEFABRIC_CELERY_RECORDS", "0")
    with pytest.raises(ValueError, match="positive"):
        _validated_count("PARSEFABRIC_CELERY_RECORDS", 100)
    monkeypatch.setenv("PARSEFABRIC_CELERY_RECORDS", "12")
    assert _validated_count("PARSEFABRIC_CELERY_RECORDS", 100) == 12


class RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.events: list[LifecycleEvent] = []

    def emit(self, event: LifecycleEvent) -> None:
        self.events.append(event)


def test_worker_job_round_trip_preserves_context() -> None:
    result = loads_result(
        parse_job(
            {
                "schema_version": "1",
                "parser_name": "application-log",
                "parser_version": "1",
                "source": "database timeout",
                "context": {
                    "source_id": "test.log",
                    "correlation_id": "c-1",
                    "partition_id": "p-1",
                    "source_offset": 100,
                },
            }
        )
    )
    assert result.events[0].evidence.source_id == "test.log"
    assert result.events[0].evidence.partition_id == "p-1"
    assert result.events[0].evidence.start_offset == 100


def test_worker_mixed_job_round_trip_preserves_results_and_evidence() -> None:
    context = ParseContext(
        source_id="mixed.txt",
        correlation_id="c-mixed",
        partition_id="p-mixed",
        source_offset=19,
    )
    result = loads_result(
        parse_job(
            {
                "schema_version": "1",
                "parser_name": MIXED_CONTENT_PARSER[0],
                "parser_version": MIXED_CONTENT_PARSER[1],
                "source": MIXED_SOURCE,
                "context": {
                    "source_id": context.source_id,
                    "correlation_id": context.correlation_id,
                    "partition_id": context.partition_id,
                    "source_offset": context.source_offset,
                },
            }
        )
    )
    expected = parse_mixed_content(MIXED_SOURCE, context)
    assert result == expected
    assert [event.evidence for event in result.events] == [
        event.evidence for event in expected.events
    ]
    assert _mixed_result_summary(result) == {
        "result_matches_local": True,
        "evidence_matches_local": True,
        "event_count": 8,
        "event_types": {
            "code": 1,
            "error": 1,
            "fence": 2,
            "json_record": 1,
            "metric": 1,
            "other": 1,
            "timeout": 1,
        },
        "provenance": {
            "parser_names": {
                "application-log": 2,
                "json": 1,
                "metrics": 1,
                "mixed-content": 4,
            },
            "pattern_names": {
                "code_fence": 3,
                "error": 1,
                "json-line": 1,
                "metric": 1,
                "other": 1,
                "timeout": 1,
            },
        },
    }
    assert MIXED_SOURCE not in json.dumps(_mixed_result_summary(result))


def test_live_verifier_expectations_match_current_mixed_fixture() -> None:
    summary = _mixed_result_summary(parse_mixed_content(MIXED_SOURCE))
    assert summary["event_types"] == EXPECTED_MIXED_EVENT_TYPES
    assert summary["event_count"] == sum(EXPECTED_MIXED_EVENT_TYPES.values())
    assert summary["provenance"]["parser_names"] == EXPECTED_MIXED_PARSER_PROVENANCE
    assert summary["provenance"]["pattern_names"] == EXPECTED_MIXED_PATTERN_PROVENANCE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("parser_name", "unknown"),
        ("parser_version", "2"),
        pytest.param("source", "a" * 1_048_577, id="oversized-source"),
        ("context", []),
    ],
)
def test_worker_rejects_incompatible_or_oversized_jobs(
    field: str, value: object
) -> None:
    job: dict[str, object] = {
        "schema_version": "1",
        "parser_name": "application-log",
        "parser_version": "1",
        "source": "database timeout",
        "context": {},
    }
    job[field] = value
    with pytest.raises(ValueError):
        _validated_job(job)


@pytest.mark.parametrize(
    ("parser_name", "parser_version"),
    [
        ("mixed-content", "2"),
        ("unknown", "1"),
    ],
)
def test_worker_rejects_unallowlisted_parser_identities(
    parser_name: str, parser_version: str
) -> None:
    with pytest.raises(ValueError, match="parser version"):
        _validated_job(
            {
                "schema_version": "1",
                "parser_name": parser_name,
                "parser_version": parser_version,
                "source": MIXED_SOURCE,
                "context": {},
            }
        )


async def test_backend_rejects_unsupported_code_before_submitting() -> None:
    class CallableSpoof:
        def __call__(self, source: str) -> None:
            pass

        def __eq__(self, other: object) -> bool:
            return True

    async with CeleryExecutionBackend() as backend:
        with pytest.raises(ValueError, match="only parse_application_log"):
            await backend.run(len, "text")
        with pytest.raises(ValueError, match="only parse_application_log"):
            await backend.run(CallableSpoof(), "text")
        with pytest.raises(ValueError, match="source"):
            await backend.run(parse_application_log, object())
        with pytest.raises(TypeError, match="ParseContext"):
            await backend.run(parse_application_log, "text", "not context")
    with pytest.raises(RuntimeError, match="shut down"):
        await backend.run(parse_application_log, "text", ParseContext())


def test_celery_accepts_only_json_serialization() -> None:
    from examples.integrations.celery_backend import celery_app

    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.result_accept_content == ["json"]


async def test_backend_transports_versioned_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResult:
        id = "example-task"

        def get(self, **kwargs: object) -> str:
            assert kwargs["propagate"] is True
            return dumps_result(parse_application_log("database timeout"))

    def submit(**kwargs: object) -> FakeResult:
        job = kwargs["kwargs"]
        assert isinstance(job, dict)
        envelope = job["job"]
        assert isinstance(envelope, dict)
        assert envelope["parser_name"] == APPLICATION_LOG_PARSER[0]
        assert envelope["parser_version"] == APPLICATION_LOG_PARSER[1]
        assert _validated_job(envelope)[0] == "database timeout"
        assert kwargs["retry"] is False
        return FakeResult()

    monkeypatch.setattr(parse_job, "apply_async", submit)
    monkeypatch.setattr(celery_app, "AsyncResult", lambda task_id: FakeResult())
    async with CeleryExecutionBackend() as backend:
        result = await backend.run(parse_application_log, "database timeout")
    assert result == parse_application_log("database timeout")


async def test_backend_waits_with_result_created_in_waiting_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_thread = threading.get_ident()

    class SubmittedResult:
        id = "example-task"

        def get(self, **kwargs: object) -> str:
            raise AssertionError("must not wait on the submitting thread's result")

    class WaitingResult:
        def __init__(self) -> None:
            self.thread = threading.get_ident()

        def get(self, **kwargs: object) -> str:
            assert self.thread == threading.get_ident() != main_thread
            assert kwargs["timeout"] == 2
            return dumps_result(parse_application_log("database timeout"))

    def make_result(task_id: str) -> WaitingResult:
        assert task_id == "example-task"
        return WaitingResult()

    monkeypatch.setattr(parse_job, "apply_async", lambda **kwargs: SubmittedResult())
    monkeypatch.setattr(celery_app, "AsyncResult", make_result)
    async with CeleryExecutionBackend(timeout=2) as backend:
        result = await backend.run(parse_application_log, "database timeout")
    assert result == parse_application_log("database timeout")


async def test_backend_transports_allowlisted_mixed_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ParseContext(source_id="mixed.txt", source_offset=5)

    class FakeResult:
        id = "example-task"

        def get(self, **kwargs: object) -> str:
            assert kwargs["propagate"] is True
            return dumps_result(parse_mixed_content(MIXED_SOURCE, context))

    def submit(**kwargs: object) -> FakeResult:
        job = kwargs["kwargs"]
        assert isinstance(job, dict)
        envelope = job["job"]
        assert isinstance(envelope, dict)
        assert envelope["parser_name"] == MIXED_CONTENT_PARSER[0]
        assert envelope["parser_version"] == MIXED_CONTENT_PARSER[1]
        assert _validated_job(envelope)[0] == MIXED_SOURCE
        assert kwargs["retry"] is False
        return FakeResult()

    monkeypatch.setattr(parse_job, "apply_async", submit)
    monkeypatch.setattr(celery_app, "AsyncResult", lambda task_id: FakeResult())
    async with CeleryExecutionBackend() as backend:
        result = await backend.run(parse_mixed_content, MIXED_SOURCE, context)
    assert result == parse_mixed_content(MIXED_SOURCE, context)


async def test_backend_surfaces_remote_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    revoked = []

    class FakeResult:
        id = "example-task"

        def get(self, **kwargs: object) -> str:
            raise CeleryTimeoutError("worker timed out")

        def revoke(self, *, terminate: bool) -> None:
            revoked.append(terminate)

    monkeypatch.setattr(parse_job, "apply_async", lambda **kwargs: FakeResult())
    monkeypatch.setattr(celery_app, "AsyncResult", lambda task_id: FakeResult())
    async with CeleryExecutionBackend(timeout=1) as backend:
        with pytest.raises(TimeoutError, match="may continue"):
            await backend.run(parse_application_log, "database timeout")
    assert revoked == [False]


async def test_backend_rejects_nonstring_worker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResult:
        id = "example-task"

        def get(self, **kwargs: object) -> object:
            return {}

    monkeypatch.setattr(parse_job, "apply_async", lambda **kwargs: FakeResult())
    monkeypatch.setattr(celery_app, "AsyncResult", lambda task_id: FakeResult())
    async with CeleryExecutionBackend() as backend:
        with pytest.raises(ValueError, match="non-string"):
            await backend.run(parse_application_log, "database timeout")


async def test_backend_propagates_remote_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResult:
        id = "example-task"

        def get(self, **kwargs: object) -> str:
            raise ValueError("worker rejected the job")

    monkeypatch.setattr(parse_job, "apply_async", lambda **kwargs: FakeResult())
    monkeypatch.setattr(celery_app, "AsyncResult", lambda task_id: FakeResult())
    async with CeleryExecutionBackend() as backend:
        with pytest.raises(ValueError, match="worker rejected"):
            await backend.run(parse_application_log, "database timeout")


async def test_backend_reports_submission_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**kwargs: object) -> None:
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(parse_job, "apply_async", fail)
    sink = RecordingSink()
    async with CeleryExecutionBackend(sink=sink) as backend:
        with pytest.raises(ConnectionError, match="broker unavailable"):
            await backend.run(parse_application_log, "database timeout")
    assert [event.name for event in sink.events] == [
        "ExecutionSubmitted",
        "ExecutionFailed",
    ]


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_backend_rejects_nonpositive_or_nonfinite_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        CeleryExecutionBackend(timeout=timeout)


@pytest.mark.parametrize("job", [None, [], "text"])
def test_worker_rejects_nonobject_envelope(job: object) -> None:
    with pytest.raises(ValueError, match="job fields"):
        _validated_job(job)


def test_worker_rejects_unknown_envelope_fields() -> None:
    job = {
        "schema_version": "1",
        "parser_name": "application-log",
        "parser_version": "1",
        "source": "database timeout",
        "context": {},
        "callable": "unallowlisted",
    }
    with pytest.raises(ValueError, match="job fields"):
        _validated_job(job)


async def test_live_verifier_waits_for_rejections_in_the_waiting_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs: dict[str, dict[str, object]] = {}

    class SubmittedResult:
        def __init__(self, task_id: str) -> None:
            self.id = task_id

        def get(self, **kwargs: object) -> str:
            raise AssertionError("verifier must not move a result between threads")

    class WaitingResult:
        def __init__(self, task_id: str) -> None:
            self.task_id = task_id
            self.thread_id = threading.get_ident()

        def get(self, **kwargs: object) -> str:
            assert self.thread_id == threading.get_ident()
            return parse_job(jobs[self.task_id])

    def submit(**kwargs: object) -> SubmittedResult:
        envelope = kwargs["kwargs"]
        assert isinstance(envelope, dict)
        job = envelope["job"]
        assert isinstance(job, dict)
        task_id = str(len(jobs))
        jobs[task_id] = job
        return SubmittedResult(task_id)

    monkeypatch.setenv("PARSEFABRIC_CELERY_RECORDS", "1")
    monkeypatch.setenv("PARSEFABRIC_CELERY_SAMPLES", "1")
    monkeypatch.delenv("PARSEFABRIC_MIN_RECORDS_PER_SECOND", raising=False)
    monkeypatch.setattr(parse_job, "apply_async", submit)
    monkeypatch.setattr(celery_app, "AsyncResult", WaitingResult)
    monkeypatch.setattr(celery_app.control, "ping", lambda **kwargs: ["ready"])
    await main()
    assert len(jobs) == 5


async def test_backend_cancellation_revokes_without_terminating_running_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    released = threading.Event()
    revocations: list[bool] = []

    class FakeResult:
        id = "cancelled-task"

        def get(self, **kwargs: object) -> str:
            started.set()
            if not released.wait(timeout=2):
                raise AssertionError("cancelled waiter was not released")
            return dumps_result(parse_application_log("database timeout"))

        def revoke(self, *, terminate: bool) -> None:
            revocations.append(terminate)
            released.set()

    monkeypatch.setattr(parse_job, "apply_async", lambda **kwargs: FakeResult())
    monkeypatch.setattr(celery_app, "AsyncResult", lambda task_id: FakeResult())
    sink = RecordingSink()
    async with CeleryExecutionBackend(sink=sink) as backend:
        task = asyncio.create_task(
            backend.run(parse_application_log, "database timeout")
        )
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            released.set()
    assert revocations == [False]
    assert [event.name for event in sink.events] == [
        "ExecutionSubmitted",
        "ExecutionStarted",
        "ExecutionCancelled",
    ]


async def test_map_failure_verifier_consumes_both_failures_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from examples.integrations.celery_example import verify_map_failure_cleanup

    jobs: dict[str, dict[str, object]] = {}

    class RemoteResult:
        def __init__(self, task_id: str) -> None:
            self.id = task_id

        def get(self, **kwargs: object) -> str:
            return parse_job(jobs[self.id])

    def submit(*args: object, **kwargs: object) -> RemoteResult:
        envelope = kwargs["kwargs"]
        assert isinstance(envelope, dict)
        job = envelope["job"]
        assert isinstance(job, dict)
        task_id = str(len(jobs))
        jobs[task_id] = job
        return RemoteResult(task_id)

    monkeypatch.setattr(parse_job, "apply_async", submit)
    monkeypatch.setattr(celery_app, "AsyncResult", RemoteResult)
    await verify_map_failure_cleanup()
    assert [job["schema_version"] for job in jobs.values()] == ["2", "2", "1"]
