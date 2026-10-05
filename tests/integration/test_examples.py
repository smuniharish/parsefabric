"""The offline examples run and print exactly their recorded output."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import verify_examples


def _completed(**fields: Any) -> Any:
    return lambda *args, **kwargs: SimpleNamespace(
        **({"returncode": 0, "stdout": "", "stderr": ""} | fields)
    )


@pytest.mark.slow
def test_offline_examples_print_their_recorded_output() -> None:
    assert verify_examples.verify() == list(verify_examples.OFFLINE)


def test_failing_examples_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify_examples.subprocess, "run", _completed(returncode=1, stderr="boom")
    )
    with pytest.raises(RuntimeError, match="boom"):
        verify_examples.verify()


def test_silent_examples_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_examples.subprocess, "run", _completed(stdout=" \n"))
    with pytest.raises(RuntimeError, match="printed no example output"):
        verify_examples.verify()


def test_changed_output_is_reported_as_a_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_examples, "OFFLINE", ("quickstart.py",))
    monkeypatch.setattr(
        verify_examples.subprocess, "run", _completed(stdout="different\n")
    )
    with pytest.raises(RuntimeError, match=r"(?s)example output changed.*\+different"):
        verify_examples.verify()


def test_update_records_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(verify_examples, "EXPECTED", tmp_path / "expected")
    monkeypatch.setattr(verify_examples, "OFFLINE", ("quickstart.py",))
    monkeypatch.setattr(verify_examples.subprocess, "run", _completed(stdout="ok\n"))
    assert verify_examples.verify(update=True) == ["quickstart.py"]
    assert (tmp_path / "expected" / "quickstart.txt").read_text() == "ok\n"
    assert verify_examples.verify() == ["quickstart.py"]
