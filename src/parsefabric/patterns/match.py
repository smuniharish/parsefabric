"""Normalized pattern match data."""

from __future__ import annotations

from dataclasses import dataclass, field

from parsefabric.models import Attributes


@dataclass(frozen=True, slots=True)
class PatternMatch:
    """What a pattern extracted from a matching value.

    Attributes:
        attributes: JSON-compatible attributes of the event to create.
        severity: Severity of the event, if any.
        confidence: Confidence between 0 and 1, if estimated.
    """

    attributes: Attributes = field(default_factory=dict)
    severity: str | None = None
    confidence: float | None = None
