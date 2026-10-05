"""Export lifecycle events as OpenTelemetry spans and as structured logs.

ParseFabric emits lifecycle events but never configures telemetry; the
application does. This example uses an in-memory span exporter and a
structlog renderer so that it prints what an observability backend would
receive.

Run: python examples/observability.py
"""

import asyncio
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser
from parsefabric.observability import (
    LoggingObservabilitySink,
    OpenTelemetryObservabilitySink,
)

LOG = "ERROR database timeout\nWARN slow disk\n"


def render(_: Any, __: str, event: MutableMapping[str, Any]) -> str:
    attributes = " ".join(
        f"{key}={value}" for key, value in sorted(event["event_attributes"].items())
    )
    return f"  {event['parsefabric_event']:<22} {attributes}".rstrip()


async def main() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    engine = ParseEngine(OpenTelemetryObservabilitySink(provider.get_tracer("shop")))
    parser = ApplicationLogParser()
    context = ParseContext(source_id="shop.log")
    result = await engine.parse(parser, LOG, context)
    await engine.aggregate(parser, result.events)
    print("spans:")
    for span in exporter.get_finished_spans():
        print(f"  {span.name}: {[event.name for event in span.events]}")

    structlog.configure(
        processors=[render], logger_factory=structlog.PrintLoggerFactory()
    )
    print("structured log records:")
    await ParseEngine(LoggingObservabilitySink()).parse(parser, LOG, context)


if __name__ == "__main__":
    asyncio.run(main())
