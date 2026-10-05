# API reference

The API reference is generated from the docstrings in the source code, so it
always matches the installed version. Every module listed here is public and
covered by the [versioning policy](../development/contributing.md#versioning).
Modules and names that start with an underscore are internal and can change
without notice.

## Modules

| Module | Contents |
| --- | --- |
| [`parsefabric.engine`](engine.md) | `ParseEngine`: parse, stream, aggregate, merge and materialize |
| [`parsefabric.models`](models.md) | `ParsedEvent`, `Evidence`, `ParseContext`, `ParseResult`, `PatternStatistic` |
| [`parsefabric.parser`](parser.md) | `Parser`, `DeterministicParser`, `AsyncParser`, `SemanticParser` |
| [`parsefabric.capabilities`](capabilities.md) | `ParserCapabilities` |
| [`parsefabric.patterns`](patterns.md) | `RegexPattern`, `ExactPattern`, `PredicatePattern`, `StructuredPattern` |
| [`parsefabric.builtins`](builtins.md) | Built-in parsers and `CodeDetector` |
| [`parsefabric.aggregation`](aggregation.md) | Lossless evidence aggregates, the wire format and statistical counting |
| [`parsefabric.execution`](execution.md) | Asyncio, thread and process execution backends |
| [`parsefabric.partitioning`](partitioning.md) | `LinePartitioner` and `Partition` |
| [`parsefabric.observability`](observability.md) | Lifecycle events and observability sinks |
| [`parsefabric.serialization`](serialization.md) | JSON and NDJSON encoding of parse results |
| [`parsefabric.compression`](compression.md) | Compression and token-savings metrics |
| [`parsefabric.registry`](registry.md) | `ParserRegistry` and plugin discovery |
| [`parsefabric.summarization`](summarization.md) | `EvidenceSummarizer` for language-model reports |
| [`parsefabric.errors`](errors.md) | Exceptions and `ParseIssue` |

## The `parsefabric` namespace

The most common names are re-exported from the package root, so most
applications only need `from parsefabric import ...`:

| Area | Names |
| --- | --- |
| Engine | `ParseEngine` |
| Models | `ParsedEvent`, `Evidence`, `ParseContext`, `ParseResult`, `PatternStatistic` |
| Parsers | `Parser`, `DeterministicParser`, `AsyncParser`, `SemanticParser`, `ParserCapabilities` |
| Aggregation | `Aggregate`, `Aggregator`, `EvidenceAggregate`, `EvidenceAggregator`, `EvidenceEntry`, `EvidenceGroup`, `RoutingAggregator` |
| Compression | `CompressionMetrics`, `measure_compression` |
| Errors | `ParseFabricError`, `ParseError`, `ConfigurationError`, `CapabilityError`, `IntegrityError`, `SerializationError`, `RegistryError`, `DuplicateParserError`, `SummaryValidationError`, `ParseIssue` |
| Constants | `MAX_JSON_DEPTH`, `__version__` |

Built-in parsers live in `parsefabric.builtins`, patterns in
`parsefabric.patterns`, and execution backends in `parsefabric.execution`.
