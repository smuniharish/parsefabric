"""Structured lifecycle events and the sinks that publish them."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

import structlog
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, Tracer

if TYPE_CHECKING:
    from collections.abc import Iterable
    from contextlib import AbstractContextManager

__all__ = [
    "CompositeObservabilitySink",
    "LifecycleEvent",
    "LifecycleValue",
    "LoggingObservabilitySink",
    "NullObservabilitySink",
    "ObservabilitySink",
    "OpenTelemetryObservabilitySink",
    "publish",
]

type LifecycleValue = str | int | float | bool | None

_LOGGER = logging.getLogger("parsefabric.observability")

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SPAN_STARTS = {
    "ParserSelected": "parse",
    "ExecutionSubmitted": "execution",
    "AggregationStarted": "aggregation",
    "MaterializeStarted": "materialize",
}
_SPAN_ENDS = {
    "ParseCompleted": ("parse", False),
    "ParseFailed": ("parse", True),
    "ParseCancelled": ("parse", False),
    "ExecutionCompleted": ("execution", False),
    "ExecutionFailed": ("execution", True),
    "ExecutionCancelled": ("execution", False),
    "AggregationCompleted": ("aggregation", False),
    "AggregationFailed": ("aggregation", True),
    "AggregationCancelled": ("aggregation", False),
    "MaterializeCompleted": ("materialize", False),
    "MaterializeFailed": ("materialize", True),
    "MaterializeCancelled": ("materialize", False),
}


def _is_scalar(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """An operational event emitted while parsing, executing or aggregating.

    Attributes:
        name: Event name, such as ``"ParseCompleted"``.
        occurred_at: Timezone-aware time of the event.
        parser_name: Parser involved, if any.
        partition_id: Partition involved, if any.
        attributes: Scalar details such as counts or an error type; never
            parsed content.
    """

    name: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    parser_name: str | None = None
    partition_id: str | None = None
    attributes: dict[str, LifecycleValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.utcoffset() is None:
            raise ValueError("lifecycle event timestamps must be timezone-aware")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("lifecycle event name must not be empty")
        if any(
            value is not None and not isinstance(value, str)
            for value in (self.parser_name, self.partition_id)
        ):
            raise ValueError("lifecycle event identifiers must be strings")
        if not isinstance(self.attributes, dict) or any(
            not isinstance(key, str) or not _is_scalar(value)
            for key, value in self.attributes.items()
        ):
            raise ValueError("lifecycle event attributes must be scalar JSON values")
        object.__setattr__(self, "attributes", dict(self.attributes))


class ObservabilitySink(ABC):
    """Application-owned destination for lifecycle events.

    Subclass it to send events anywhere: a metrics client, a message queue, a
    test recorder. Only `emit` is required; override `flush` and `close` when
    the destination buffers events or holds connections.

    ParseFabric awaits `emit` inline in parsing and execution code, so keep it
    fast. An exception raised by a sink is logged on the
    ``parsefabric.observability`` logger and never fails the operation that
    emitted the event.
    """

    @abstractmethod
    async def emit(self, event: LifecycleEvent) -> None:
        """Publish one lifecycle event.

        Args:
            event: The event to publish.
        """

    async def flush(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Deliver buffered events. The default does nothing."""

    async def close(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Flush and release resources. The default does nothing."""


class NullObservabilitySink(ObservabilitySink):
    """Sink that discards every lifecycle event."""

    @override
    async def emit(self, event: LifecycleEvent) -> None:
        del event


class CompositeObservabilitySink(ObservabilitySink):
    """Fan every event out to several sinks, in order.

    A failing child sink is logged and skipped; the remaining sinks still
    receive the event.

    Args:
        sinks: Sinks that receive every event.
    """

    def __init__(self, sinks: Iterable[ObservabilitySink]) -> None:
        self._sinks = tuple(sinks)
        if not all(isinstance(sink, ObservabilitySink) for sink in self._sinks):
            raise TypeError("composite sinks must be ObservabilitySink instances")

    @property
    def sinks(self) -> tuple[ObservabilitySink, ...]:
        """The child sinks, in delivery order."""
        return self._sinks

    @override
    async def emit(self, event: LifecycleEvent) -> None:
        for sink in self._sinks:
            await publish(sink, event)

    @override
    async def flush(self) -> None:
        """Flush every child sink, then raise any failures together.

        Raises:
            ExceptionGroup: If one or more child sinks failed to flush.
        """
        await self._each("flush")

    @override
    async def close(self) -> None:
        """Close every child sink, then raise any failures together.

        Raises:
            ExceptionGroup: If one or more child sinks failed to close.
        """
        await self._each("close")

    async def _each(self, operation: str) -> None:
        errors: list[Exception] = []
        for sink in self._sinks:
            try:
                await getattr(sink, operation)()
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup(
                f"{len(errors)} observability sink(s) failed to {operation}", errors
            )


async def publish(sink: ObservabilitySink, event: LifecycleEvent) -> None:
    """Emit ``event`` to ``sink``, logging instead of raising on sink errors.

    ParseFabric publishes every lifecycle event through this function. Call it
    from custom execution backends or partitioners so that a broken sink never
    breaks the operation being observed.

    Args:
        sink: Destination sink.
        event: The event to publish.
    """
    if type(sink) is NullObservabilitySink:
        return
    try:
        await sink.emit(event)
    except Exception:
        _LOGGER.exception("observability sink %s failed on %s", type(sink).__name__, event.name)


class LoggingObservabilitySink(ObservabilitySink):
    """Write lifecycle events as structured log records with structlog.

    ParseFabric does not configure structlog; the application decides the
    rendering and destination.

    Args:
        logger: Logger to use. Defaults to ``structlog.get_logger(
            "parsefabric.lifecycle")``.
    """

    def __init__(self, logger: structlog.stdlib.BoundLogger | None = None) -> None:
        self._logger = (
            logger if logger is not None else structlog.get_logger("parsefabric.lifecycle")
        )

    @override
    async def emit(self, event: LifecycleEvent) -> None:
        self._logger.info(
            "parsefabric.lifecycle",
            parsefabric_event=event.name,
            parser_name=event.parser_name,
            partition_id=event.partition_id,
            event_attributes=dict(event.attributes),
            occurred_at=event.occurred_at.isoformat(),
        )


def _nanoseconds(moment: datetime) -> int:
    """Return exact integer nanoseconds since the Unix epoch."""
    delta = moment - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


class OpenTelemetryObservabilitySink(ObservabilitySink):
    """Record lifecycle events as OpenTelemetry spans and span events.

    Start events (``ParserSelected``, ``ExecutionSubmitted``,
    ``AggregationStarted``, ``MaterializeStarted``) open a span named
    ``parsefabric.<operation>`` that nests under the innermost open operation
    of the same task; the matching completion, failure or cancellation event
    ends it, failures with an error status. Other events become span events.
    An event outside any operation is attached to the active span, or else
    recorded in a short ``parsefabric.lifecycle`` span.

    ParseFabric does not configure an OpenTelemetry SDK or exporter. Without
    application configuration the API's no-op provider records nothing.

    Args:
        tracer: Tracer to use. Defaults to ``trace.get_tracer("parsefabric")``.
    """

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._tracer = tracer or trace.get_tracer("parsefabric")
        self._operation_spans: ContextVar[
            tuple[tuple[str, Span, AbstractContextManager[Span]], ...]
        ] = ContextVar(f"parsefabric_spans_{id(self)}", default=())

    @override
    async def emit(self, event: LifecycleEvent) -> None:
        timestamp = _nanoseconds(event.occurred_at)
        attributes: dict[str, str | int | float | bool] = {
            "parsefabric.event.name": event.name,
        }
        if event.parser_name is not None:
            attributes["parsefabric.parser.name"] = event.parser_name
        if event.partition_id is not None:
            attributes["parsefabric.partition.id"] = event.partition_id
        attributes.update(
            {
                f"parsefabric.{key}": value
                for key, value in event.attributes.items()
                if value is not None
            }
        )

        stack = self._operation_spans.get()
        operation = _SPAN_STARTS.get(event.name)
        if operation is not None:
            parent_context = trace.set_span_in_context(stack[-1][1]) if stack else None
            span = self._tracer.start_span(
                f"parsefabric.{operation}",
                context=parent_context,
                attributes=attributes,
                start_time=timestamp,
            )
            span_scope = trace.use_span(span, end_on_exit=False)
            span_scope.__enter__()
            self._operation_spans.set((*stack, (operation, span, span_scope)))
            span.add_event(event.name, attributes=attributes, timestamp=timestamp)
            return

        terminal = _SPAN_ENDS.get(event.name)
        if stack:
            stack[-1][1].add_event(event.name, attributes=attributes, timestamp=timestamp)
            if terminal is not None:
                operation_name, failed = terminal
                for index in range(len(stack) - 1, -1, -1):
                    if stack[index][0] == operation_name:
                        _, completed_span, completed_scope = stack[index]
                        self._operation_spans.set(stack[:index] + stack[index + 1 :])
                        if failed:
                            error_type = attributes.get("parsefabric.error_type")
                            completed_span.set_status(
                                Status(
                                    StatusCode.ERROR,
                                    str(error_type) if error_type is not None else None,
                                )
                            )
                        completed_scope.__exit__(None, None, None)
                        completed_span.end(end_time=timestamp)
                        break
            return

        active_span = trace.get_current_span()
        if active_span.get_span_context().is_valid and active_span.is_recording():
            active_span.add_event(event.name, attributes=attributes, timestamp=timestamp)
            return

        with self._tracer.start_as_current_span(
            "parsefabric.lifecycle",
            attributes=attributes,
            start_time=timestamp,
            end_on_exit=True,
        ) as span:
            span.add_event(event.name, attributes=attributes, timestamp=timestamp)
