# Observability

Read this when lifecycle events must reach OpenTelemetry, structlog, or your
own telemetry. The full guide is
[Observability](https://parsefabric.readthedocs.io/en/latest/guide/observability/).

## Lifecycle events

| Events | Emitted by | Attributes |
| --- | --- | --- |
| `ParserSelected`, `ParseStarted`, `ParseCompleted`, `ParseFailed`, `ParseCancelled` | `ParseEngine` parse methods | `event_count` or `error_type` |
| `PatternMatched` | `ParseEngine`, once per pattern with matches | `pattern_name`, `match_count` |
| `PartitionCompleted` | `ParseEngine`, when the context has a `partition_id` | `event_count` |
| `Aggregation*`, `Materialize*` | `aggregate`, `merge_aggregates`, `materialize` | `aggregate_count`, `event_count` or `error_type` |
| `Execution*` | Execution backends | `error_type` on failure |

Events carry no parsed content, so telemetry does not leak the data you parse.

## Sinks

All are in `parsefabric.observability`.

| Sink | Sends events to |
| --- | --- |
| `NullObservabilitySink` | Nowhere; the default |
| `LoggingObservabilitySink(logger=None)` | structlog, as `parsefabric.lifecycle` records |
| `OpenTelemetryObservabilitySink(tracer=None)` | OpenTelemetry spans named `parsefabric.parse`, `parsefabric.execution`, `parsefabric.aggregation` and `parsefabric.materialize` |
| `CompositeObservabilitySink([...])` | Several sinks |

Pass a sink to `ParseEngine(sink)`, to execution backends, and to
`LinePartitioner`:

<!-- docs-test: skip -->
```python
from parsefabric import ParseEngine
from parsefabric.observability import OpenTelemetryObservabilitySink

engine = ParseEngine(OpenTelemetryObservabilitySink(provider.get_tracer("log-ingest")))
```

## Rules

- Configure the OpenTelemetry SDK, its exporter and structlog in the
  application, at start-up. ParseFabric never configures them.
- Shut down the tracer provider before exit, so batched spans are flushed.
- `opentelemetry-api` and `structlog` are core dependencies; the SDK and an
  exporter, such as `opentelemetry-exporter-otlp-proto-http`, are the
  application's.
- To send events somewhere else, subclass `ObservabilitySink`; the
  parsefabric-extend skill covers that.
