# Testing extensions

`parsefabric.testing` holds one contract check per extension point. Each
check exercises the rules on the extension's page and raises
`AssertionError` with a message naming the broken rule. Call them from your
test suite, with any async test runner:

| Check | For |
| --- | --- |
| `check_parser(parser, source, context=None)` | [`Parser`](parsers.md) |
| `check_parser_registry(registry, parsers)` | [`ParserRegistry`](registries.md) |
| `check_pattern(pattern, matching, other)` | [`Pattern`](patterns.md) |
| `check_aggregator(aggregator, events)` | [`Aggregator`](aggregators.md) |
| `check_codec(codec, aggregates)` | [`AggregateCodec`](codecs.md) |
| `check_json_codec(codec)` | [`JSONCodec`](codecs.md#json-documents) |
| `check_partitioner(partitioner, lines, capabilities=...)` | [`Partitioner`](partitioners.md) |
| `check_execution_backend(backend)` | [`ExecutionBackend`](execution-backends.md) |
| `check_observability_sink(sink)` | [`ObservabilitySink`](observability-sinks.md) |
| `check_language_model(model)` | [`LanguageModel`](language-models.md) |
| `check_tokenizer(tokenizer, samples=...)` | [`Tokenizer`](tokenizers.md) |
| `check_code_detector(detector, expected)` | [`CodeDetector`](code-detectors.md) |
| `check_command_output_backend(backend, command, output)` | [`CommandOutputBackend`](command-output-backends.md) |

Every check is async except `check_pattern`, because `Pattern.match` is
synchronous. Checks return what they produced, such as the parse result or
the aggregates, so tests can make further assertions.

With pytest and [pytest-asyncio](https://pytest-asyncio.readthedocs.io/):

<!-- docs-test: skip -->
```python
import pytest

from parsefabric.builtins import ApplicationLogParser
from parsefabric.testing import check_aggregator, check_parser

pytestmark = pytest.mark.asyncio


async def test_parser_honors_the_contract() -> None:
    result = await check_parser(ApplicationLogParser(), "db timeout\nall good\n")
    assert [event.event_type for event in result.events] == ["timeout"]


async def test_aggregator_honors_the_contract() -> None:
    parser = ApplicationLogParser()
    result = await check_parser(parser, "db timeout\ndb timeout\n")
    aggregates = await check_aggregator(parser.aggregator, result.events)
    assert sum(aggregate.count for aggregate in aggregates) == 2
```

The checks import nothing beyond ParseFabric itself, so they run in any
test framework.
