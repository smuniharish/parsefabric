"""Base parser contract with package-managed aggregation and serialization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Iterable
from typing import cast, final

from parsefabric.aggregation import (
    Aggregate,
    Aggregator,
    EvidenceAggregate,
    EvidenceAggregator,
    codec,
)
from parsefabric.capabilities import ParserCapabilities
from parsefabric.models import Evidence, ParseContext, ParsedEvent, ParseResult

_PACKAGE_MANAGED = frozenset(
    {"aggregator", "aggregate", "merge_aggregates", "serialize", "deserialize"}
)


def _evidence(aggregates: Iterable[Aggregate]) -> tuple[EvidenceAggregate, ...]:
    # Package-managed aggregators produce only evidence aggregates.
    return cast("tuple[EvidenceAggregate, ...]", tuple(aggregates))


def validated_identity(name: object, version: object) -> tuple[str, str]:
    """Return a parser name and version if both are non-empty strings."""
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(version, str)
        or not (version)
    ):
        raise ValueError("parser name and version must not be empty strings")
    return name, version


class Parser(ABC):
    """Turn one input into a `ParseResult`.

    A parser implements `parse` and declares its `name`,
    `version` and `capabilities`. Aggregation and serialization
    are managed by ParseFabric: every parser produces the same lossless
    grouped evidence in the same closed wire format, and subclasses cannot
    override `aggregator`, `aggregate`, `merge_aggregates`,
    `serialize` or `deserialize`.
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

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        overridden = sorted(_PACKAGE_MANAGED & cls.__dict__.keys())
        if not cls.__module__.startswith("parsefabric."):
            overridden += [
                name for name in ("_build_aggregator",) if name in cls.__dict__
            ]
        if overridden:
            raise TypeError(
                f"{cls.__qualname__} cannot define {', '.join(overridden)}: "
                "aggregation and serialization are managed by ParseFabric; "
                "implement parse instead"
            )

    @final
    @property
    def aggregator(self) -> Aggregator:
        """The package-managed lossless aggregator for this parser's events.

        Events of deterministic, stateless parsers are referenced by line
        position and re-parsed on materialize; all other parsers retain their
        events. Evidence entries carry the string ``message`` attribute,
        otherwise all event attributes, or ``None`` when there are none.
        """
        return self._build_aggregator()

    def _build_aggregator(self) -> Aggregator:
        capabilities = self.capabilities
        return EvidenceAggregator(
            reproducible=capabilities.deterministic and not capabilities.stateful,
        )

    @final
    async def aggregate(
        self, events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent]
    ) -> tuple[EvidenceAggregate, ...]:
        """Aggregate the events of one source document into grouped evidence.

        Args:
            events: Events of one source, in source order.

        Returns:
            Lossless evidence aggregates.
        """
        return _evidence(await self.aggregator.aggregate(events))

    @final
    async def merge_aggregates(
        self, partials: Iterable[Aggregate] | AsyncIterable[Aggregate]
    ) -> tuple[EvidenceAggregate, ...]:
        """Combine aggregates of distinct source documents.

        Args:
            partials: Aggregates to combine.

        Returns:
            The combined aggregates.
        """
        return _evidence(await self.aggregator.merge(partials))

    @final
    def serialize(
        self, aggregates: Iterable[EvidenceAggregate], *, indent: int | None = None
    ) -> str:
        """Encode evidence in the ``parsefabric.aggregates/1`` wire format.

        Args:
            aggregates: Aggregates to encode.
            indent: Indentation for human reading; compact when ``None``.

        Returns:
            JSON text; non-ASCII characters are written as UTF-8.
        """
        return codec.encode(aggregates, indent=indent)

    @final
    def deserialize(self, text: str | bytes) -> tuple[EvidenceAggregate, ...]:
        """Decode and validate `serialize` output.

        Args:
            text: JSON text or UTF-8 bytes.

        Returns:
            The validated aggregates.

        Raises:
            SerializationError: For malformed or unsupported documents.
        """
        return codec.decode(text)

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
                source_id=evidence.source_id
                or (context.source_id if context else None),
                start_offset=(
                    start_offset if start_offset is not None else evidence.start_offset
                ),
                end_offset=(
                    end_offset if end_offset is not None else evidence.end_offset
                ),
                line_number=(
                    line_number if line_number is not None else evidence.line_number
                ),
                parser_name=evidence.parser_name or self.name,
                parser_version=evidence.parser_version or self.version,
                pattern_name=pattern_name or evidence.pattern_name,
                partition_id=evidence.partition_id
                or (context.partition_id if context else None),
                correlation_id=evidence.correlation_id
                or (context.correlation_id if context else None),
            )
        )
