"""The parser contract and its default aggregation behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING, Generic, cast

from typing_extensions import TypeVar

from parsefabric.aggregation import Aggregate, EvidenceAggregate, EvidenceAggregator
from parsefabric.models import Evidence, ParseContext, ParsedEvent, ParseResult

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Iterable

    from parsefabric.aggregation import Aggregator
    from parsefabric.capabilities import ParserCapabilities

AggregateT_co = TypeVar("AggregateT_co", bound=Aggregate, covariant=True, default=EvidenceAggregate)
"""Aggregate type a parser's aggregator produces; `EvidenceAggregate` by default."""


def validated_identity(name: object, version: object) -> tuple[str, str]:
    """Return a parser name and version if both are non-empty strings."""
    if not isinstance(name, str) or not name or not isinstance(version, str) or not (version):
        raise ValueError("parser name and version must not be empty strings")
    return name, version


class Parser(ABC, Generic[AggregateT_co]):
    """Turn one input into a `ParseResult`.

    A parser implements `parse` and declares its `name`, `version` and
    `capabilities`. Aggregation is delegated to `aggregator`, which defaults
    to a lossless `EvidenceAggregator`; override `build_aggregator` to use
    another `Aggregator` and parameterize the class with its aggregate type,
    as in ``class CountingParser(DeterministicParser[CountAggregate])``.
    Storage of aggregates is the job of the `ParseEngine` codec, not of the
    parser.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable parser name recorded in evidence and used by registries."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Version of the parser's implementation and configuration."""

    @property
    @abstractmethod
    def capabilities(self) -> ParserCapabilities:
        """Behavioral guarantees that orchestration code relies on."""

    @abstractmethod
    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        """Parse one input.

        Args:
            source: The input, typically text or bytes.
            context: Where the input comes from.

        Returns:
            Events with evidence, plus any recorded issues and statistics.
        """

    @cached_property
    def aggregator(self) -> Aggregator[AggregateT_co]:
        """The aggregator for this parser's events.

        Built once by `build_aggregator` on first use and reused by
        `aggregate`, `merge_aggregates` and the engine.
        """
        return self.build_aggregator()

    def build_aggregator(self) -> Aggregator[AggregateT_co]:
        """Return the aggregator for this parser's events.

        The default is a lossless `EvidenceAggregator`: events of
        deterministic, stateless parsers are referenced by line position and
        re-parsed on materialize; all other parsers retain their events.
        Override it to return any `Aggregator`, such as an `EventAggregator`
        for lossy counts or your own implementation.

        Returns:
            A new aggregator.
        """
        capabilities = self.capabilities
        aggregator = EvidenceAggregator(
            reproducible=capabilities.deterministic and not capabilities.stateful,
        )
        # Parsers parameterized with another aggregate type override this method.
        return cast("Aggregator[AggregateT_co]", aggregator)

    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[AggregateT_co, ...]:
        """Aggregate the events of one source document with `aggregator`.

        Args:
            events: Events of one source, in source order.

        Returns:
            The aggregates.
        """
        return await self.aggregator.aggregate(events)

    async def merge_aggregates(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[AggregateT_co, ...]:
        """Combine aggregates of distinct source documents with `aggregator`.

        Args:
            partials: Aggregates to combine.

        Returns:
            The combined aggregates.
        """
        return await self.aggregator.merge(partials)

    def _with_parser_evidence(
        self,
        event: ParsedEvent,
        context: ParseContext | None,
        *,
        start_offset: int | None = None,
        end_offset: int | None = None,
        line_number: int | None = None,
        pattern_name: str | None = None,
    ) -> ParsedEvent:
        evidence = event.evidence
        return event.with_evidence(
            Evidence(
                source_id=evidence.source_id or (context.source_id if context else None),
                start_offset=(start_offset if start_offset is not None else evidence.start_offset),
                end_offset=(end_offset if end_offset is not None else evidence.end_offset),
                line_number=(line_number if line_number is not None else evidence.line_number),
                parser_name=evidence.parser_name or self.name,
                parser_version=evidence.parser_version or self.version,
                pattern_name=pattern_name or evidence.pattern_name,
                partition_id=evidence.partition_id or (context.partition_id if context else None),
                correlation_id=evidence.correlation_id
                or (context.correlation_id if context else None),
            )
        )
