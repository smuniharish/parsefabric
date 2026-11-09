# Changelog

All notable changes to ParseFabric are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-09

ParseFabric is stable: every component is an abstract base class with a
default implementation, everything that can do I/O or call user code is
`async`, and every extension point ships a contract check.

### Added

- Abstract base classes for every replaceable component, each injected
  through the constructor of the component that uses it: `Parser`,
  `AsyncParser`, `SemanticParser`, `Pattern`, `Aggregator`, `AggregateCodec`,
  `JSONCodec`, `Partitioner`, `ExecutionBackend`, `ObservabilitySink`,
  `LanguageModel`, `ParserRegistry`, `Tokenizer`, `CodeDetector` and
  `CommandOutputBackend`.
- `parsefabric.testing`, with one contract check per abstract base class
  (`check_parser`, `check_codec`, `check_execution_backend`, and so on).
- `LanguageModel`, a provider-neutral model interface with structured
  output. `SemanticParser` and `EvidenceSummarizer` accept any
  implementation.
- `parsefabric.integrations.langchain` (the `langchain` extra):
  `LangChainLanguageModel` adapts any LangChain chat model, `parser_tool`
  exposes a parser as an agent tool, and `parser_node` turns it into an async
  LangGraph node.
- `ExecutorBackend` runs parsing on any `concurrent.futures.Executor`.
  Execution backends accept async iterables.
- `CodeDetector.prepare()` fetches tree-sitter grammars explicitly; no
  constructor touches the network.
- `ParseIssue.input_index` and the original traceback for every recorded
  failure.
- A throughput benchmark gate for regressions.
- Python 3.15 support.
- Two Agent Skills: `parsefabric` for applications and `parsefabric-extend`
  for extensions, each with references, offline scripts, tested templates and
  evaluations. Both install with `npx skills add smuniharish/parsefabric`.

### Changed

- Observability sinks, partitioners, codecs, registry discovery, code
  detection and command-output parsing are `async`. jc and tree-sitter work
  runs off the event loop. A failing sink never breaks a parse.
- `EvidenceSummarizer` runs on plain asyncio, with bounded concurrency and
  timeouts.
- Evidence aggregates store repeated events more compactly: a bursty log is
  stored 91% smaller than its source, up from 82%.
- Thread backends keep one event loop per worker. Thread, process and
  executor backends take a `shutdown_timeout`.
- Capabilities are cached, results built by the package are not revalidated,
  JSON is decoded in a single pass, and code detection is incremental.
- Routing order is deterministic, and `materialize` keeps the correlation and
  partition identifiers of its context.
- Strict JSON uses the standard library.
- Packaging uses `uv_build`, every dependency is on its latest stable
  release, and type checking uses pyrefly.
- The documentation is built with Zensical and has an Extending section with
  one guide per abstract base class.

### Fixed

- Spans no longer leak when aggregation or materialization is cancelled.
- Malformed critic output no longer consumes a summary revision.
- jc and fenced-block parser errors are reported instead of dropped.

## [0.1.0] - 2026-10-05

The first public release.

### Added

- `ParseEngine` to parse single inputs and streams, with input-order
  (`parse_iter`, `parse_many`) and bounded-concurrency (`parse_async_iter`)
  streaming, evidence completion from `ParseContext`, and optional error
  tolerance that records failures as `ParseIssue` values.
- Immutable, validated models: `ParsedEvent`, `Evidence`, `ParseContext`,
  `ParseResult` and `PatternStatistic`, with strict JSON and NDJSON
  serialization (`dumps_result`, `loads_result`, `iter_ndjson`).
- The parser contract `Parser` with declared `ParserCapabilities`, the
  pattern-based `DeterministicParser`, and `AsyncParser` and `SemanticParser`
  for I/O-bound and model-backed parsing.
- Patterns: `RegexPattern`, `ExactPattern`, `PredicatePattern` and
  `StructuredPattern`.
- Built-in parsers: `ApplicationLogParser`, `TimestampedLogParser`,
  `JSONParser`, `PythonTracebackParser`, `CLIOutputParser` (backed by jc) and
  `MixedContentParser` with routes, fence routes and tree-sitter
  `CodeDetector`.
- Lossless evidence aggregation managed by the package, the versioned
  `parsefabric.aggregates/1` wire format with SHA-256 checksums, verified
  materialization, statistical counting with `EventAggregator`, and
  compression metrics.
- Execution backends for asyncio, threads and spawn-based processes, and
  `LinePartitioner` for parsing large documents in independent partitions.
- Lifecycle events with OpenTelemetry and structlog sinks.
- `ParserRegistry` with entry-point plugin discovery.
- `EvidenceSummarizer` for language-model reports over aggregates, with
  deterministic claim checks, model critique and bounded revision.
- Runnable examples with recorded output, reference integrations for Celery,
  Apache Spark and Apache Flink, and an Agent Skill for AI coding agents.

[Unreleased]: https://github.com/smuniharish/parsefabric/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/smuniharish/parsefabric/releases/tag/v1.0.0
[0.1.0]: https://pypi.org/project/parsefabric/0.1.0/
