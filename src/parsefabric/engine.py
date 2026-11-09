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
from typing import TYPE_CHECKING

from parsefabric.codecs import AggregateCodec, EvidenceCodec
from parsefabric.errors import CapabilityError, ParseIssue
from parsefabric.models import ParseContext, ParsedEvent, ParseResult
from parsefabric.observability import (
    LifecycleEvent,
    LifecycleValue,
    NullObservabilitySink,
    ObservabilitySink,
    publish,
)

if TYPE_CHECKING:
    from parsefabric.aggregation import Aggregate
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

    The engine is independent of where work runs: it awaits parsers directly,
    reports lifecycle events to an `ObservabilitySink` and stores aggregates
    with an `AggregateCodec`. Both are extension points.

    Args:
        sink: Destination for lifecycle events. Defaults to a sink that
            discards them.
        codec: Format used by `serialize` and `deserialize`. Defaults to
            `EvidenceCodec`.

    Raises:
        TypeError: If ``sink`` or ``codec`` has the wrong type.
    """

    def __init__(
        self,
        sink: ObservabilitySink | None = None,
        *,
        codec: AggregateCodec | None = None,
    ) -> None:
        if sink is not None and not isinstance(sink, ObservabilitySink):
            raise TypeError("sink must be an ObservabilitySink")
        if codec is not None and not isinstance(codec, AggregateCodec):
            raise TypeError("codec must be an AggregateCodec")
        self._sink = sink if sink is not None else NullObservabilitySink()
        self._observed = type(self._sink) is not NullObservabilitySink
        self._codec = codec if codec is not None else EvidenceCodec()

    @property
    def sink(self) -> ObservabilitySink:
        """The sink receiving lifecycle events."""
        return self._sink

    @property
    def codec(self) -> AggregateCodec:
        """The codec used by `serialize` and `deserialize`."""
        return self._codec

    async def _emit(
        self,
        name: str,
        parser: Parser[Aggregate],
        partition_id: str | None = None,
        **attributes: LifecycleValue,
    ) -> None:
        if self._observed:
            await publish(
                self._sink,
                LifecycleEvent(
                    name,
                    parser_name=parser.name,
                    partition_id=partition_id,
                    attributes=attributes,
                ),
            )

    async def parse(
        self,
        parser: Parser[Aggregate],
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
        return await self._parse(parser, source, context, continue_on_error, None)

    async def _parse(
        self,
        parser: Parser[Aggregate],
        source: object,
        context: ParseContext | None,
        continue_on_error: bool,
        input_index: int | None,
    ) -> ParseResult:
        partition_id = context.partition_id if context else None
        await self._emit("ParserSelected", parser)
        await self._emit("ParseStarted", parser, partition_id)
        try:
            result = await parser.parse(source, context)
        except asyncio.CancelledError:
            await self._emit("ParseCancelled", parser, partition_id)
            raise
        except Exception as error:
            await self._emit("ParseFailed", parser, partition_id, error_type=type(error).__name__)
            if not continue_on_error:
                raise
            return ParseResult(
                errors=(
                    ParseIssue.from_exception(
                        error,
                        source_id=context.source_id if context else None,
                        input_index=input_index,
                    ),
                ),
                parser_name=parser.name,
                parser_version=parser.version,
                correlation_id=context.correlation_id if context else None,
            )

        enriched = self._enrich(parser, result, context)
        if self._observed:
            for statistic in enriched.pattern_statistics:
                if statistic.matches:
                    await self._emit(
                        "PatternMatched",
                        parser,
                        pattern_name=statistic.pattern_name,
                        match_count=statistic.matches,
                    )
            if partition_id is not None:
                await self._emit(
                    "PartitionCompleted", parser, partition_id, event_count=len(enriched.events)
                )
            await self._emit(
                "ParseCompleted", parser, partition_id, event_count=len(enriched.events)
            )
        return enriched

    @staticmethod
    def _enrich(
        parser: Parser[Aggregate],
        result: ParseResult,
        context: ParseContext | None,
    ) -> ParseResult:
        def enrich_event(event: ParsedEvent) -> ParsedEvent:
            evidence = event.evidence
            source_id = evidence.source_id or (context.source_id if context else None)
            parser_name = evidence.parser_name or parser.name
            parser_version = evidence.parser_version or parser.version
            partition_id = evidence.partition_id or (context.partition_id if context else None)
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

        events = tuple(enrich_event(event) for event in result.events)
        parser_name = result.parser_name or parser.name
        parser_version = result.parser_version or parser.version
        correlation_id = result.correlation_id or (context.correlation_id if context else None)
        # Built-in parsers already fill every field; skip rebuilding their results.
        if (
            parser_name == result.parser_name
            and parser_version == result.parser_version
            and correlation_id == result.correlation_id
            and all(new is old for new, old in zip(events, result.events, strict=True))
        ):
            return result
        return ParseResult(
            events=events,
            warnings=result.warnings,
            errors=result.errors,
            pattern_statistics=result.pattern_statistics,
            parser_name=parser_name,
            parser_version=parser_version,
            correlation_id=correlation_id,
            llm_result=result.llm_result,
        )

    async def parse_iter(
        self,
        parser: Parser[Aggregate],
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
            One enriched result per input. Issues recorded with
            ``continue_on_error`` carry the input's zero-based ``input_index``.
        """
        index = 0
        async for source in _iterate(sources):
            yield await self._parse(parser, source, context, continue_on_error, index)
            index += 1

    async def parse_async_iter(
        self,
        parser: Parser[Aggregate],
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
            One enriched result per input. Issues recorded with
            ``continue_on_error`` carry the input's zero-based ``input_index``,
            which identifies the input when results arrive out of order.

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
        index = 0
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
                                self._parse(parser, source, context, continue_on_error, index)
                            )
                        )
                        index += 1
                if not pending:
                    return
                completed, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in completed:
                    pending.remove(task)
                    yield task.result()
        except asyncio.CancelledError:
            await self._emit("ParseCancelled", parser)
            raise
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await inputs.aclose()

    async def parse_many(
        self,
        parser: Parser[Aggregate],
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
            The enriched results in input order. Issues recorded with
            ``continue_on_error`` carry the input's zero-based ``input_index``.
        """
        return tuple(
            [
                result
                async for result in self.parse_iter(
                    parser, sources, context=context, continue_on_error=continue_on_error
                )
            ]
        )

    async def aggregate[AggregateT: Aggregate](
        self,
        parser: Parser[AggregateT],
        events: Iterable[ParsedEvent] | AsyncIterable[ParsedEvent],
    ) -> tuple[AggregateT, ...]:
        """Aggregate events with the parser's `Parser.aggregator`.

        Args:
            parser: Parser whose events are aggregated.
            events: Events of one source document, in source order.

        Returns:
            The aggregates; lossless `EvidenceAggregate` items by default.

        Raises:
            CapabilityError: If the parser is not aggregatable.
        """
        return await self._observe_aggregation(parser, lambda: parser.aggregate(events))

    async def merge_aggregates[AggregateT: Aggregate](
        self,
        parser: Parser[AggregateT],
        partials: Iterable[Aggregate] | AsyncIterable[Aggregate],
    ) -> tuple[AggregateT, ...]:
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
        return await self._observe_aggregation(parser, lambda: parser.merge_aggregates(partials))

    async def _observe_aggregation[AggregateT: Aggregate](
        self,
        parser: Parser[Aggregate],
        operation: Callable[[], Awaitable[tuple[AggregateT, ...]]],
    ) -> tuple[AggregateT, ...]:
        if not parser.capabilities.aggregatable:
            raise CapabilityError("parser capabilities do not allow aggregation")
        await self._emit("AggregationStarted", parser)
        try:
            result = await operation()
        except asyncio.CancelledError:
            await self._emit("AggregationCancelled", parser)
            raise
        except Exception as error:
            await self._emit("AggregationFailed", parser, error_type=type(error).__name__)
            raise
        await self._emit("AggregationCompleted", parser, aggregate_count=len(result))
        return result

    async def materialize(
        self,
        parser: Parser[Aggregate],
        source: object,
        aggregates: Iterable[Aggregate],
        context: ParseContext | None = None,
    ) -> tuple[ParsedEvent, ...]:
        """Rebuild every original event from lossless aggregates and verify it.

        When the parser's aggregator requires the source, ``source`` is parsed
        again with ``context``; otherwise the events retained in the
        aggregates are used. The aggregates are rebuilt from those candidate
        events and must match exactly, including their SHA-256 checksums.

        Args:
            parser: Parser that produced the aggregates.
            source: The original input.
            aggregates: Every aggregate of the source document.
            context: Context of the original parse. Defaults to one carrying
                only the aggregates' ``source_id``; pass the original context
                when it also set partition or correlation identifiers.

        Returns:
            The verified original events in source order.

        Raises:
            CapabilityError: If the parser's aggregator is lossy.
            IntegrityError: If the events do not reproduce the aggregates.
        """
        selected = tuple(aggregates)
        aggregator = parser.aggregator
        if not aggregator.lossless:
            raise CapabilityError(
                f"{type(aggregator).__name__} is a lossy aggregator and cannot materialize"
            )
        await self._emit("MaterializeStarted", parser)
        try:
            events = None
            if aggregator.requires_source:
                if context is None:
                    source_id = getattr(selected[0], "source_id", None) if selected else None
                    context = ParseContext(
                        source_id=source_id if isinstance(source_id, str) else None
                    )
                events = (await self.parse(parser, source, context)).events
            result = await aggregator.materialize(selected, events)
        except asyncio.CancelledError:
            await self._emit("MaterializeCancelled", parser)
            raise
        except Exception as error:
            await self._emit("MaterializeFailed", parser, error_type=type(error).__name__)
            raise
        await self._emit("MaterializeCompleted", parser, event_count=len(result))
        return result

    async def serialize(self, aggregates: Iterable[Aggregate], *, indent: int | None = None) -> str:
        """Encode aggregates with the engine's `codec`.

        Args:
            aggregates: Aggregates to store or transport.
            indent: Indentation for human reading, if the codec supports it.

        Returns:
            The encoded document.
        """
        return await self._codec.encode(aggregates, indent=indent)

    async def deserialize(self, data: str | bytes) -> tuple[Aggregate, ...]:
        """Decode and validate a document produced by `serialize`.

        Args:
            data: Encoded text or bytes.

        Returns:
            The validated aggregates.

        Raises:
            SerializationError: If ``data`` is not a valid document.
        """
        return await self._codec.decode(data)
