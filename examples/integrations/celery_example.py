"""Run the maintained Celery checks and reconstruct remote mixed evidence."""

import asyncio
import gc
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import celery

from examples.integrations.celery_backend import (
    CeleryExecutionBackend,
    main,
    parse_application_log,
    parse_job,
    parse_mixed_content,
)
from examples.integrations.mixed_job import MIXED_SOURCE, mixed_parser
from examples.integrations.result_checks import verify_materialization
from parsefabric.models import ParseContext
from parsefabric.observability import LifecycleEvent, ObservabilitySink


class _RecordingSink(ObservabilitySink):
    def __init__(self) -> None:
        self.events: list[LifecycleEvent] = []

    def emit(self, event: LifecycleEvent) -> None:
        self.events.append(event)


async def verify_map_failure_cleanup() -> None:
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda loop, context: unhandled.append(context))
    sink = _RecordingSink()
    rejected = 0
    both_rejected = asyncio.Event()
    submit = parse_job.apply_async

    def incompatible_submission(*args: object, **kwargs: Any) -> Any:
        envelope = kwargs["kwargs"]
        kwargs["kwargs"] = {
            "job": dict(envelope["job"], schema_version="2"),
        }
        return submit(*args, **kwargs)

    try:
        async with CeleryExecutionBackend(sink=sink) as backend:
            run = backend.run

            async def synchronized_failure(
                function: Callable[..., Any], *args: object, **kwargs: object
            ) -> Any:
                nonlocal rejected
                try:
                    return await run(function, *args, **kwargs)
                except ValueError as error:
                    if "schema version" not in str(error):
                        raise
                    rejected += 1
                    if rejected == 2:
                        both_rejected.set()
                    await asyncio.wait_for(both_rejected.wait(), timeout=30)
                    raise

            # Both failures originate on the real worker; only their client-side
            # completion is synchronized to exercise simultaneous map cleanup.
            with (
                patch.object(parse_job, "apply_async", incompatible_submission),
                patch.object(backend, "run", synchronized_failure),
            ):
                try:
                    async for _ in backend.map(
                        parse_application_log,
                        ["database timeout", "connection refused"],
                        max_in_flight=2,
                    ):
                        raise AssertionError(
                            "incompatible map job unexpectedly succeeded"
                        )
                except ValueError as error:
                    if "schema version" not in str(error):
                        raise
                else:
                    raise AssertionError("map did not propagate the worker failure")
            gc.collect()
            await asyncio.sleep(0)
            if rejected != 2 or unhandled:
                raise AssertionError(
                    f"map cleanup lost failures: rejected={rejected}, "
                    f"unhandled={unhandled}"
                )
            if sum(event.name == "ExecutionFailed" for event in sink.events) != 2:
                raise AssertionError("map did not observe both remote task failures")
            result = await backend.run(parse_application_log, "database timeout")
            if result != parse_application_log("database timeout"):
                raise AssertionError("backend could not recover after failed mapping")
    finally:
        loop.set_exception_handler(previous_handler)
    print(
        "Celery map cleanup verified: 2 real worker failures propagated/consumed, "
        "0 unhandled task exceptions, subsequent remote job succeeded",
        flush=True,
    )


async def verify() -> None:
    print(f"Celery runtime: {celery.__version__}", flush=True)
    await main()
    context = ParseContext(
        source_id="materialization.txt",
        correlation_id="celery-materialization",
        partition_id="mixed-0",
        source_offset=23,
    )
    async with CeleryExecutionBackend() as backend:
        result = await backend.run(parse_mixed_content, MIXED_SOURCE, context)
    verify_materialization(mixed_parser(), MIXED_SOURCE, context, result)
    print("Celery remote mixed-content materialization verified", flush=True)
    await verify_map_failure_cleanup()


if __name__ == "__main__":
    asyncio.run(verify())
