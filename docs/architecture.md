# Architecture

ParseFabric is a small set of composable layers: parsers turn input into
events with evidence, the engine runs parsers and completes their evidence,
aggregation stores events losslessly, and execution backends decide where
work runs. Each layer depends only on the contracts of the layers below it.

<figure class="diagram" markdown="span">
  ![Inputs and parsers feed the parse engine or partitioned execution backends, which produce parse results; results become lossless evidence aggregates that can be serialized, materialized or summarized; the engine sends lifecycle events to observability sinks.](assets/diagrams/architecture.png){ width="600" }
  <figcaption>The main components and how data flows between them.</figcaption>
</figure>

## Components

| Component | Responsibility |
| --- | --- |
| Models | Immutable, validated events, evidence, contexts and results |
| Patterns | Named, prioritized rules that recognize a value and produce an event |
| Parsers | Turn one input into a result and declare their capabilities |
| Built-in parsers | Application and timestamped logs, JSON, tracebacks, command output and mixed content |
| Engine | Runs parsers on single inputs and streams, completes evidence, tolerates failures on request, and reports lifecycle events |
| Aggregation | Groups events into checksummed evidence, encodes the wire format, and rebuilds events |
| Execution | Runs callables on the event loop, threads, processes or custom infrastructure, with bounded concurrency |
| Partitioning | Splits large line-oriented documents into independent partitions |
| Observability | Lifecycle events and sinks for OpenTelemetry and structlog |
| Registry | Names parsers and discovers installed parser plugins |
| Summarization | Language-model reports over aggregates, with every claim checked |

## Design principles

**Evidence first.** Every event records its source, line, byte span, pattern
and parser version, so any finding can be traced back to the exact input that
produced it.

**Lossless by default.** Aggregation is managed by the package, not by
individual parsers, and every aggregate carries a checksum. Materializing
either returns exactly the original events or raises `IntegrityError`.

**Strict boundaries.** Results and aggregates use versioned JSON formats with
exact field sets. Decoding rejects unknown fields, duplicate keys, non-finite
numbers and inconsistent counts instead of guessing.

**Explicit capabilities.** Parsers declare whether they are deterministic,
parallel-safe, stateful or partitionable, and orchestration code checks those
declarations before it schedules concurrent or partitioned work.

**Asynchronous core, pluggable execution.** Parsing is `async` throughout.
Parsers do not know where they run; backends decide, and the same parser
produces the same results on every backend.

**No hidden global state.** There is no global registry, and ParseFabric never
configures logging, telemetry export or a model provider. Applications own
those decisions.

**Language models are optional and checked.** The core parsers are
deterministic. Model-backed parsing and summaries are opt-in, see only the
data you give them, and never return unchecked claims as checked.

## Extension points

| Extend | By |
| --- | --- |
| Line formats | Building a `DeterministicParser` from patterns |
| Other formats | Subclassing `Parser`, `AsyncParser` or `SemanticParser` |
| Mixed documents | Adding routes and fence routes to `MixedContentParser` |
| Where work runs | Subclassing `ExecutionBackend` |
| Where telemetry goes | Subclassing `ObservabilitySink` |
| Plugin distribution | Publishing parsers in the `parsefabric.parsers` entry-point group |

## Learn more

| Topic | Page |
| --- | --- |
| The parse flow and evidence | [Parsing and evidence](guide/parsing.md) |
| How mixed documents are classified | [Mixed content](guide/mixed-content.md) |
| How aggregates are built and verified | [Aggregation and storage](guide/aggregation.md) |
| Streaming, backends and partitioning | [Streaming and execution](guide/execution.md) |
| The summary review process | [Evidence summaries](guide/summaries.md) |
