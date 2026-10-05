"""Shared pytest configuration, Hypothesis profiles and fixtures."""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, settings

from tests.support.paths import EXAMPLE_DATA

settings.register_profile(
    "ci",
    max_examples=300,
    deadline=None,
    derandomize=True,
    database=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "dev",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "thorough",
    max_examples=2_000,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


@pytest.fixture(scope="session")
def example_data() -> Callable[[str], str]:
    """Return a reader for UTF-8 files under ``examples/data``."""

    def read(name: str) -> str:
        return (EXAMPLE_DATA / name).read_text(encoding="utf-8")

    return read
