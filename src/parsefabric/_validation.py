"""Argument validation shared across modules."""

from __future__ import annotations

import math


def validated_timeout(name: str, value: object) -> float | None:
    """Return ``value`` as seconds if it is ``None`` or a positive finite number.

    Raises:
        ValueError: If ``value`` is anything else; the message names ``name``.
    """
    if value is None:
        return None
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive finite number or None")
    return float(value)
