# Observability

ParseFabric reports what it does as **lifecycle events**: a parse started, a
pattern matched, an aggregation failed, a partition was created. You decide
where they go by passing a sink to the engine, the execution backends and the
partitioner. Lifecycle events carry counts, names and error types, never
parsed content, so telemetry does not leak the data you parse.

ParseFabric never configures logging or telemetry export itself. Without a
sink, events are discarded.

## Lifecycle events

| Event | Emitted by | Attributes |
| --- | --- | --- |
| `ParserSelected`, `ParseStarted` | `ParseEngine` parse methods | |
| `PatternMatched` | `ParseEngine`, once per pattern with matches | `pattern_name`, `match_count` |
| `PartitionCompleted` | `ParseEngine`, when the context has a `partition_id` | `event_count` |
| `ParseCompleted` | `ParseEngine` | `event_count` |
| `ParseFailed` | `ParseEngine` | `error_type` |
| `ParseCancelled` | `ParseEngine` | |
| `AggregationStarted`, `AggregationCompleted`, `AggregationFailed` | `ParseEngine.aggregate` and `merge_aggregates` | `aggregate_count` or `error_type` |
| `MaterializeStarted`, `MaterializeCompleted`, `MaterializeFailed` | `ParseEngine.materialize` | `event_count` or `error_type` |
| `ExecutionSubmitted`, `ExecutionStarted`, `ExecutionCompleted`, `ExecutionFailed`, `ExecutionCancelled` | Execution backends | `error_type` on failure |
| `PartitionCreated` | `LinePartitioner` | `line_count`, `byte_count` |

Every event also records its time (`occurred_at`) and, where it applies, the
`parser_name` and `partition_id`.

## Sinks

| Sink | Records events as |
| --- | --- |
| `NullObservabilitySink` | Nothing; the default |
| `LoggingObservabilitySink` | structlog records named `parsefabric.lifecycle`, with the fields `parsefabric_event`, `parser_name`, `partition_id`, `event_attributes` and `occurred_at` |
| `OpenTelemetryObservabilitySink` | OpenTelemetry spans and span events |

The OpenTelemetry sink opens a span for each operation (`parsefabric.parse`,
`parsefabric.execution`, `parsefabric.aggregation` and
`parsefabric.materialize`), nested under the innermost open operation of the
same task, and records the lifecycle events as span events. Failures set the
span status to `ERROR`. Span attributes are prefixed with `parsefabric.`, such
as `parsefabric.parser.name` and `parsefabric.event_count`.

```python
--8<--
examples/observability.py
--8<--
```

Output:

```text
--8<-- "examples/expected/observability.txt"
```

## Export traces

The OpenTelemetry API records nothing until your application configures an
SDK. To send spans to a collector over OTLP, install
`opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-http` and set up a
tracer provider at startup:

<!-- docs-test: skip -->
```python
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from parsefabric import ParseEngine
from parsefabric.observability import OpenTelemetryObservabilitySink

provider = TracerProvider(resource=Resource.create({"service.name": "log-ingest"}))
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces"))
)
engine = ParseEngine(OpenTelemetryObservabilitySink(provider.get_tracer("log-ingest")))
```

Call `provider.shutdown()` when the application exits so that buffered spans
are flushed.

## Write a sink

Subclass `ObservabilitySink` and implement `emit`, for example to feed
metrics. Sinks run inline in parsing and execution code, so they must be fast
and must not raise:

```python
import asyncio
from collections import Counter

from parsefabric import ParseEngine
from parsefabric.builtins import ApplicationLogParser
from parsefabric.observability import LifecycleEvent, ObservabilitySink


class CountingSink(ObservabilitySink):
    """Count lifecycle events by name."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def emit(self, event: LifecycleEvent) -> None:
        self.counts[event.name] += 1


async def main() -> None:
    sink = CountingSink()
    engine = ParseEngine(sink)
    inputs = ["db timeout", "all good", b"\xff"]
    async for _ in engine.parse_iter(
        ApplicationLogParser(), inputs, continue_on_error=True
    ):
        pass
    print(dict(sorted(sink.counts.items())))


asyncio.run(main())
```

Output:

```text
{'ParseCompleted': 2, 'ParseFailed': 1, 'ParseStarted': 3, 'ParserSelected': 3, 'PatternMatched': 1}
```
