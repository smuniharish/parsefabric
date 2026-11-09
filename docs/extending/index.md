# Extending ParseFabric

Every part of ParseFabric that you might want to replace is an abstract base
class with a default implementation. Subclass the ABC, implement its abstract
methods, and pass an instance to the component that uses it. There is no
global registry and no monkey-patching: what runs is what you construct.

| Extension point | Default | Pass it to | Contract check |
| --- | --- | --- | --- |
| [`Parser`](parsers.md), `AsyncParser`, `SemanticParser` | The built-in parsers | `ParseEngine` methods, registries, routes | `check_parser` |
| [`Pattern`](patterns.md) | `RegexPattern`, `ExactPattern`, `PredicatePattern`, `StructuredPattern` | `DeterministicParser`, `MixedContentParser(routes=)` | `check_pattern` |
| [`Aggregator`](aggregators.md) | `EvidenceAggregator` | A parser's `build_aggregator` | `check_aggregator` |
| [`AggregateCodec`](codecs.md) | `EvidenceCodec` | `ParseEngine(codec=)` | `check_codec` |
| [`JSONCodec`](codecs.md#json-documents) | `StrictJSONCodec` | `JSONParser(codec=)` | `check_json_codec` |
| [`Partitioner`](partitioners.md) | `LinePartitioner` | Your partitioned pipeline | `check_partitioner` |
| [`ExecutionBackend`](execution-backends.md) | `AsyncExecutionBackend`, `ThreadExecutionBackend`, `ProcessExecutionBackend`, `ExecutorBackend` | Your pipeline | `check_execution_backend` |
| [`ObservabilitySink`](observability-sinks.md) | `NullObservabilitySink` | `ParseEngine`, execution backends, `LinePartitioner` | `check_observability_sink` |
| [`LanguageModel`](language-models.md) | None; `LangChainLanguageModel` with the `langchain` extra | `EvidenceSummarizer`, `SemanticParser` | `check_language_model` |
| [`ParserRegistry`](registries.md) | `InMemoryParserRegistry` | Your application | `check_parser_registry` |
| [`Tokenizer`](tokenizers.md) | `ApproximateTokenizer` | `measure_compression(tokenizer=)` | `check_tokenizer` |
| [`CodeDetector`](code-detectors.md) | `TreeSitterCodeDetector` | `MixedContentParser(code_detector=)` | `check_code_detector` |
| [`CommandOutputBackend`](command-output-backends.md) | `JcBackend` | `CLIOutputParser(backend=)` | `check_command_output_backend` |

## Rules every extension follows

**Asynchronous where it matters.** Methods that may do I/O, call user code
or do heavy work are coroutines, so an implementation can await a service
without blocking the event loop. Offload blocking or CPU-bound work with
`asyncio.to_thread`. Only per-line pattern matching and value-object
validation stay synchronous, because they sit on the hot path.

**Abstract base classes, not protocols.** An extension subclasses its ABC, so
a missing method fails when the class is instantiated rather than deep inside
a run, and `isinstance` checks are reliable.

**Constructor injection.** Components receive their collaborators when they
are created, and the defaults are module-level instances that hold no
per-run state.

**Verified by contract checks.** `parsefabric.testing` checks an
implementation against the rules the rest of the package relies on. The
built-in implementations pass every check; see
[Test your extensions](testing.md).
