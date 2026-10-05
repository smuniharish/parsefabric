"""Pattern for structured mapping inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from parsefabric.patterns.predicate import PredicatePattern


class StructuredPattern(PredicatePattern):
    """Match mapping-shaped records, such as decoded JSON objects.

    Non-mapping values never match and never reach the callables.

    Args:
        name: Pattern name.
        predicate: Returns whether a mapping matches.
        extractor: Returns the attributes of a matched mapping; defaults to
            the mapping itself.
        priority: Evaluation priority; higher runs first.
        metadata: Free-form description kept on the pattern.
        event_type: Event type of produced events; defaults to ``name``.
        severity: Severity of produced events.
    """

    def __init__(
        self,
        name: str,
        predicate: Callable[[Mapping[str, Any]], bool],
        extractor: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        *,
        priority: int = 0,
        metadata: Mapping[str, Any] | None = None,
        event_type: str | None = None,
        severity: str | None = None,
    ) -> None:
        if not callable(predicate) or (
            extractor is not None and not callable(extractor)
        ):
            raise ValueError("predicate and extractor must be callable")

        def mapping_predicate(value: object) -> bool:
            return isinstance(value, Mapping) and predicate(value)

        def mapping_extractor(value: object) -> Mapping[str, Any]:
            # Only called after mapping_predicate accepted the value.
            mapping = cast("Mapping[str, Any]", value)
            return extractor(mapping) if extractor is not None else mapping

        super().__init__(
            name,
            mapping_predicate,
            mapping_extractor,
            priority=priority,
            metadata=metadata,
            event_type=event_type,
            severity=severity,
        )
