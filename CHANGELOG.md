# Changelog

All notable changes to ParseFabric are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - Unreleased

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

[Unreleased]: https://github.com/smuniharish/parsefabric/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/smuniharish/parsefabric/releases/tag/v0.1.0
