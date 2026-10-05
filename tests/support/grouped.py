"""Readable views of evidence aggregates for assertions."""

from parsefabric.aggregation import Aggregate, EvidenceAggregate
from parsefabric.models import JSONValue

Row = tuple[str | None, JSONValue, str, int]


def line_refs(positions: tuple[int | None, ...]) -> str:
    """Render 1-based line positions such as ``2,3,4``; ``?`` when unknown."""
    return ",".join("?" if line is None else str(line) for line in positions)


def rows(document: Aggregate) -> list[Row]:
    """``(severity, message, line positions, occurrences)`` per evidence entry."""
    assert isinstance(document, EvidenceAggregate)
    return [
        (group.severity, entry.message, line_refs(entry.positions), entry.occurrences)
        for group in document.groups
        for entry in group.evidence
    ]
