"""Run parsers on inputs and streams; aggregate, merge and materialize evidence."""

from __future__ import annotations

import asyncio
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
)
from dataclasses import replace

from parsefabric.aggregation import Aggregate, EvidenceAggregate
from parsefabric.errors import CapabilityError, ParseIssue
from parsefabric.models import ParseContext, ParsedEvent, ParseResult
from parsefabric.observability import (
    LifecycleEvent,
    NullObservabilitySink,
    ObservabilitySink,
)
from parsefabric.parser import Parser

__all__ = [
    "ParseEngine",
]


async def _iterate[T](
    items: Iterable[T] | AsyncIterable[T],
) -> AsyncGenerator[T, None]:
    """Yield the items of a synchronous or asynchronous iterable."""
    if isinstance(items, AsyncIterable):
        async for item in items:
            yield item
    else:
        for item in items:
            yield item


class ParseEngine:
    """Run parsers over single inputs or streams and enrich their evidence.

    The engine is independent of where work runs: it awaits parsers directly
    and reports lifecycle events to an optional
    `ObservabilitySink`.

    Args:
        sink: Destination for lifecycle events. Defaults to a sink that
            discards them.
    """

    def __init__(self, sink: ObservabilitySink | None = None) -> None:
        self._sink = sink or NullObservabilitySink()

    async def parse(
        self,
        parser: Parser,
        source: object,
        context: ParseContext | None = None,
        *,
        continue_on_error: bool = False,
    ) -> ParseResult:
        """Parse one input and fill in missing evidence from the context.

        Events whose evidence already names the source, parser, version,
        partition and correlation are returned unchanged; missing fields are
        filled from ``context`` and the parser identity.

        Args:
            parser: Parser to run.
            source: Input value accepted by ``parser``.
            context: Caller-supplied source, correlation, partition and offset.
            continue_on_error: Return a result containing a
                `ParseIssue` instead of raising
                when the parser fails.

        Returns:
            The enriched parse result.

        Raises:
            Exception: Any parser exception when ``continue_on_error`` is
                false. Cancellation always propagates.
        """
        partition_id = context.partition_id if context else None
        self._sink.emit(LifecycleEvent("ParserSelected", parser_name=parser.name))
        self._sink.emit(
            LifecycleEvent(
                "ParseStarted", parser_name=parser.name, partition_id=partition_id
            )
        )
        try:
            result = await parser.parse(source, context)
        except asyncio.CancelledError:
            self._sink.emit(
                LifecycleEvent(
                    "ParseCancelled", parser_name=parser.name, partition_id=partition_id
                )
            )
            raise
        except Exception as error:
            self._sink.emit(
                LifecycleEvent(
                    "ParseFailed",
                    parser_name=parser.name,
                    partition_id=partition_id,
                    attributes={"error_type": type(error).__name__},
                )
            )
            if not continue_on_error:
                raise
            return ParseResult(
                errors=(
                    ParseIssue.from_exception(
                        error,
                        source_id=context.source_id if context else None,
                    ),
                ),
                parser_name=parser.name,
                parser_version=parser.version,
                correlation_id=context.correlation_id if context else None,
            )

        enriched = self._enrich(parser, result, context)
        self._emit_pattern_matches(parser, enriched)
        if partition_id is not None:
            self._sink.emit(
                LifecycleEvent(
                    "PartitionCompleted",
                    parser_name=parser.name,
                    partition_id=partition_id,
                    attributes={"event_count": len(enriched.events)},
                )
            )
        self._sink.emit(
            LifecycleEvent(
                "ParseCompleted",
                parser_name=parser.name,
                partition_id=partition_id,
                attributes={"event_count": len(enriched.events)},
            )
        )
        return enriched

    def _emit_pattern_matches(self, parser: Parser, result: ParseResult) -> None:
        for statistic in result.pattern_statistics:
            if statistic.matches:
                self._sink.emit(
                    LifecycleEvent(
                        "PatternMatched",
                        parser_name=parser.name,
                        attributes={
                            "pattern_name": statistic.pattern_name,
                            "match_count": statistic.matches,
                        },
                    )
                )

    @staticmethod
    def _enrich(
        parser: Parser,
        result: ParseResult,
        context: ParseContext | None,
    ) -> ParseResult:
        def enrich_event(event: ParsedEvent) -> ParsedEvent:
            evidence = event.evidence
            source_id = evidence.source_id or (context.source_id if context else None)
            parser_name = evidence.parser_name or parser.name
            parser_version = evidence.parser_version or parser.version
            partition_id = evidence.partition_id or (
                context.partition_id if context else None
            )
            correlation_id = evidence.correlation_id or (
                context.correlation_id if context else None
            )
            if (
                source_id == evidence.source_id
                and parser_name == evidence.parser_name
                and parser_version == evidence.parser_version
                and partition_id == evidence.partition_id
                and correlation_id == evidence.correlation_id
            ):
                return event
            return event.with_evidence(
                replace(
                    evidence,
                    source_id=source_id,
                    parser_name=parser_name,
                    parser_version=parser_version,
                    partition_id=partition_id,
                    correlation_id=correlation_id,
                )
            )

        return ParseResult(
            events=tuple(enrich_event(event) for event in result.events),
            warnings=result.warnings,
            errors=result.errors,
            pattern_statistics=result.pattern_statistics,
            parser_name=result.parser_name or parser.name,
            parser_version=result.parser_version or parser.version,
            correlation_id=result.correlation_id
            or (context.correlation_id if context else None),
            llm_result=result.llm_result,
        )

    async def parse_iter(
        self,
        parser: Parser,
        sources: Iterable[object] | AsyncIterable[object],
        *,
        context: ParseContext | None = None,
        continue_on_error: bool = False,
    ) -> AsyncIterator[ParseResult]:
        """Parse inputs one at a time, yielding each result in input order.

        Args:
            parser: Parser to run for every input.
            sources: Synchronous or asynchronous iterable of inputs.
            context: Context applied to every input.
            continue_on_error: See `parse`.

        Yields:
            One enriched result per input.
        """
        async for source in _iterate(sources):
            yield await self.parse(
                parser, source, context, continue_on_error=continue_on_error
            )

    async def parse_async_iter(
        self,
        parser: Parser,
        sources: Iterable[object] | AsyncIterable[object],
        *,
        max_concurrency: int = 1,
        context: ParseContext | None = None,
        continue_on_error: bool = False,
    ) -> AsyncIterator[ParseResult]:
        """Parse inputs concurrently with a bound on outstanding work.

        At most ``max_concurrency`` inputs are parsed at once. With more than
        one, results are yielded in completion order. Closing or cancelling
        the iterator cancels outstanding parses and consumes their outcomes.

        Args:
            parser: Parser to run; it must be parallel-safe when
                ``max_concurrency`` is greater than one.
            sources: Synchronous or asynchronous iterable of inputs.
            max_concurrency: Maximum number of parses in flight.
            context: Context applied to every input.
            continue_on_error: See `parse`.

        Yields:
            One enriched result per input.

        Raises:
            ValueError: If ``max_concurrency`` is not a positive integer.
            CapabilityError: If concurrency is requested for a parser that is
                not parallel-safe.
        """
        if type(max_concurrency) is not int or max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        if max_concurrency > 1:
            parser.capabilities.require_parallel_safe()
        inputs = _iterate(sources)
        pending: set[asyncio.Task[ParseResult]] = set()
        exhausted = False
        try:
            while True:
                while not exhausted and len(pending) < max_concurrency:
                    try:
                        source = await anext(inputs)
                    except StopAsyncIteration:
                        exhausted = True
                    else:
                        pending.add(
                            asyncio.create_task(
                                self.parse(
                                    parser,
                                    source,
                                    context,
                                    continue_on_error=continue_on_error,
                                )
                            )
                        )
                if not pending:
                    return
                completed, _ = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in completed:
                    pending.remove(task)
                    yield task.result()
        except asyncio.CancelledError:
            self._sink.emit(LifecycleEvent("ParseCancelled", parser_name=parser.name))
            raise
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await inputs.aclose()

    async def parse_many(
        self,
        parser: Parser,
        sources: Iterable[object] | AsyncIterable[object],
        *,
        context: ParseContext | None = None,
        continue_on_error: bool = False,
    ) -> tuple[ParseResult, ...]:
        """Parse a finite batch sequentially and return every result.

        Args:
            parser: Parser to run for every input.
            sources: Synchronous or asynchronous iterable of inputs.
            context: Context applied to every input.
            continue_on_error: See `parse`.

        Returns:
            The enriched results in input order.
        """
        return tuple(
            [
                await self.parse(
                    parser, source, context, continue_on_error=continue_on_error
                )
                async for source in _iterate(sources)
            ]
        )

    async def aggregate(
        self,
        parser: Parser,
        events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent],
    ) -> tuple[EvidenceAggregate, ...]:
        """Aggregate events with the parser's package-managed aggregator.

        Args:
            parser: Parser whose events are aggregated.
            events: Events of one source document, in source order.

        Returns:
            Lossless evidence aggregates.

        Raises:
            CapabilityError: If the parser is not aggregatable.
        """
        return await self._observe_aggregation(parser, lambda: parser.aggregate(events))

    async def merge_aggregates(
        self,
        parser: Parser,
        partials: Iterable[Aggregate] | AsyncIterable[Aggregate],
    ) -> tuple[EvidenceAggregate, ...]:
        """Combine aggregates of distinct source documents.

        Args:
            parser: Parser that produced the aggregates.
            partials: Aggregates to combine.

        Returns:
            The combined aggregates.

        Raises:
            CapabilityError: If the parser is not aggregatable or the
                aggregates split one source document.
        """
        return await self._observe_aggregation(
            parser, lambda: parser.merge_aggregates(partials)
        )

    async def _observe_aggregation(
        self,
        parser: Parser,
        operation: Callable[[], Awaitable[tuple[EvidenceAggregate, ...]]],
    ) -> tuple[EvidenceAggregate, ...]:
        if not parser.capabilities.aggregatable:
            raise CapabilityError("parser capabilities do not allow aggregation")
        self._sink.emit(LifecycleEvent("AggregationStarted", parser_name=parser.name))
        try:
            result = await operation()
        except Exception as error:
            self._sink.emit(
                LifecycleEvent(
                    "AggregationFailed",
                    parser_name=parser.name,
                    attributes={"error_type": type(error).__name__},
                )
            )
            raise
        self._sink.emit(
            LifecycleEvent(
                "AggregationCompleted",
                parser_name=parser.name,
                attributes={"aggregate_count": len(result)},
            )
        )
        return result

    async def materialize(
        self,
        parser: Parser,
        source: object,
        aggregates: Iterable[Aggregate],
        context: ParseContext | None = None,
    ) -> tuple[ParsedEvent, ...]:
        """Rebuild every original event from lossless aggregates and verify it.

        When the parser's aggregator requires the source, ``source`` is parsed
        again with ``context`` (by default only the aggregates' ``source_id``);
        otherwise the events retained in the aggregates are used. The
        aggregates are rebuilt from those candidate events and must match
        exactly, including their SHA-256 checksums.

        Args:
            parser: Parser that produced the aggregates.
            source: The original input.
            aggregates: Every aggregate of the source document.
            context: Context of the original parse.

        Returns:
            The verified original events in source order.

        Raises:
            IntegrityError: If the events do not reproduce the aggregates.
        """
        selected = tuple(aggregates)
        aggregator = parser.aggregator
        self._sink.emit(LifecycleEvent("MaterializeStarted", parser_name=parser.name))
        try:
            events = None
            if aggregator.requires_source:
                if context is None:
                    source_id = (
                        getattr(selected[0], "source_id", None) if selected else None
                    )
                    context = ParseContext(
                        source_id=source_id if isinstance(source_id, str) else None
                    )
                events = (await self.parse(parser, source, context)).events
            result = await aggregator.materialize(selected, events)
        except Exception as error:
            self._sink.emit(
                LifecycleEvent(
                    "MaterializeFailed",
                    parser_name=parser.name,
                    attributes={"error_type": type(error).__name__},
                )
            )
            raise
        self._sink.emit(
            LifecycleEvent(
                "MaterializeCompleted",
                parser_name=parser.name,
                attributes={"event_count": len(result)},
            )
        )
        return result
