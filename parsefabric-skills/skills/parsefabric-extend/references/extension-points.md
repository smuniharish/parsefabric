# Extension points

Every row is an abstract base class. Implement the listed members, pass an
instance where the table says, and check it with the named function from
`parsefabric.testing`. The full guide is
[Extending ParseFabric](https://parsefabric.readthedocs.io/en/latest/extending/).

| ABC (module) | Implement | Default | Pass it to | Check |
| --- | --- | --- | --- | --- |
| `Parser` (`parsefabric`) | `name`, `version`, `capabilities`, `async parse(source, context)` | Built-in parsers | `ParseEngine` methods, registries, routes | `check_parser` |
| `AsyncParser`, `SemanticParser` (`parsefabric.parser`) | `async parse`; `name=` and `version=` (and `model=`) in the constructor | None | As `Parser` | `check_parser` |
| `Pattern` (`parsefabric.patterns`) | `match(value)`; name and event type via the constructor | `RegexPattern`, `ExactPattern`, `PredicatePattern`, `StructuredPattern` | `DeterministicParser`, `MixedContentParser(routes=)` | `check_pattern` |
| `Aggregator` (`parsefabric.aggregation`) | `async aggregate(events)`, `async merge(partials)`; optionally `lossless`, `requires_source`, `materialize` | `EvidenceAggregator` | A parser's `build_aggregator` | `check_aggregator` |
| `AggregateCodec` (`parsefabric.codecs`) | `format`, `async encode(aggregates, *, indent)`, `async decode(data)` | `EvidenceCodec` | `ParseEngine(codec=)` | `check_codec` |
| `JSONCodec` (`parsefabric.codecs`) | `async decode(text)` | `StrictJSONCodec` | `JSONParser(codec=)` | `check_json_codec` |
| `Partitioner` (`parsefabric.partitioning`) | `partition(lines, *, source_id, capabilities)`, an async iterator of `Partition` | `LinePartitioner` | The application's partitioned pipeline | `check_partitioner` |
| `ExecutionBackend` (`parsefabric.execution`) | `async run(function, *args, **kwargs)`, `async shutdown()`; `map` has a default | `AsyncExecutionBackend`, `ThreadExecutionBackend`, `ProcessExecutionBackend`, `ExecutorBackend` | The application's pipeline | `check_execution_backend` |
| `ObservabilitySink` (`parsefabric.observability`) | `async emit(event)`; optionally `flush`, `close` | `NullObservabilitySink` | `ParseEngine`, backends `sink=`, `LinePartitioner(sink=)` | `check_observability_sink` |
| `LanguageModel` (`parsefabric.llm`) | `async complete(messages) -> str`; optionally `name` | `LangChainLanguageModel` with the `langchain` extra | `EvidenceSummarizer`, `SemanticParser(model=)` | `check_language_model` |
| `ParserRegistry` (`parsefabric.registry`) | `async register_all`, `unregister`, `get`, `names` | `InMemoryParserRegistry` | The application | `check_parser_registry` |
| `Tokenizer` (`parsefabric.compression`) | `async count(text)` | `ApproximateTokenizer` | `measure_compression(tokenizer=)` | `check_tokenizer` |
| `CodeDetector` (`parsefabric.builtins.code_detection`) | `async detect(text)`; optionally `prepare` | `TreeSitterCodeDetector` | `MixedContentParser(code_detector=)` | `check_code_detector` |
| `CommandOutputBackend` (`parsefabric.builtins.cli_output`) | `name`, `validate(command)`, `async parse(command, text)` | `JcBackend` | `CLIOutputParser(backend=)` | `check_command_output_backend` |

## Contract checks in pytest

Every check except `check_pattern` is a coroutine and raises
`AssertionError` naming the broken promise:

<!-- docs-test: skip -->
```python
import asyncio

from parsefabric.testing import check_parser
from myapp.parsing import OrderLogParser


def test_order_parser_contract() -> None:
    asyncio.run(check_parser(OrderLogParser(), "order 7 failed\n"))
```

`scripts/check_extension.py` runs the same checks from the command line.
