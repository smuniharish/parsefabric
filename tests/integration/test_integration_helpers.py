import asyncio
import subprocess
import sys
import threading

import pytest

from examples.integrations.json_contract import decode_json
from examples.integrations.sync_bridge import run_sync


def test_sync_bridge_runs_without_an_existing_event_loop() -> None:
    async def value() -> int:
        await asyncio.sleep(0)
        return 42

    assert run_sync(value()) == 42


async def test_sync_bridge_uses_another_thread_inside_a_running_loop() -> None:
    caller = threading.get_ident()

    async def thread_id() -> int:
        await asyncio.sleep(0)
        return threading.get_ident()

    assert run_sync(thread_id()) != caller


@pytest.mark.parametrize("inside_loop", [False, True])
def test_sync_bridge_propagates_original_exception(inside_loop: bool) -> None:
    error = ValueError("worker failed")

    async def fail() -> None:
        raise error

    async def running() -> None:
        run_sync(fail())

    def call() -> None:
        if inside_loop:
            asyncio.run(running())
        else:
            run_sync(fail())

    with pytest.raises(ValueError) as caught:
        call()
    assert caught.value is error


@pytest.mark.parametrize(
    "payload",
    [
        '{"source":"first","source":"second"}',
        '{"context":{"source_id":"first","source_id":"second"}}',
        '{"index":NaN}',
        '{"index":Infinity}',
        '{"index":-Infinity}',
    ],
)
def test_runtime_json_decoder_rejects_ambiguous_or_nonfinite_values(
    payload: str,
) -> None:
    with pytest.raises(ValueError, match=r"duplicate JSON field|non-finite JSON"):
        decode_json(payload)


def test_base_and_noncelery_integrations_import_without_optional_runtimes() -> None:
    code = """
import importlib.abc
import sys

class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'celery', 'pyspark', 'pyflink'}:
            raise AssertionError('unexpected optional runtime import: ' + fullname)

sys.meta_path.insert(0, BlockOptional())
import parsefabric
import examples.integrations
import examples.integrations.sync_bridge
import examples.integrations.json_contract
import examples.integrations.mixed_job
import examples.integrations.spark_batch
import examples.integrations.spark_measure
import examples.integrations.flink_backend
assert not {'celery', 'pyspark', 'pyflink'}.intersection(sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
