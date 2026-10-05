---
name: parsefabric
description: Integrate, configure, extend, debug, or test the parsefabric Python library, which turns logs, JSON, command output, tracebacks and mixed text into structured events with line and byte-span evidence. Use when building parsers or patterns, routing mixed documents, aggregating, storing or rebuilding parsed events losslessly, streaming or partitioning parsing across threads, processes or clusters, wiring OpenTelemetry or structlog lifecycle events, or producing checked LLM summaries of parsed evidence.
---

# parsefabric

Use this skill for the existing `parsefabric` Python package (import name
`parsefabric`, Python 3.12+). It is a parsing library, not a log storage
service, a scheduler, or an LLM framework.

The most common imports are:

```python
from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser, MixedContentParser
from parsefabric.patterns import RegexPattern
```

The authoritative documentation is
[parsefabric.readthedocs.io](https://parsefabric.readthedocs.io/en/latest/),
and the source, examples and tests are at
[github.com/smuniharish/parsefabric](https://github.com/smuniharish/parsefabric).
Read [Parsing and evidence](https://parsefabric.readthedocs.io/en/latest/guide/parsing/)
before changing how results are produced, and the
[API reference](https://parsefabric.readthedocs.io/en/latest/reference/) before
calling any API this file does not show.

## Activate when

Use `parsefabric` when an application must extract structured events from
operational text and keep evidence of where each event came from. Typical
indicators:

- parsing application logs, timestamped logs, JSON documents, Python
  tracebacks or command output such as `df`;
- documents that mix log lines, JSON, fenced or unfenced code and prose;
- events that must be traced to a source, line, byte span and pattern;
- storing repetitive events compactly and rebuilding them exactly later;
- parsing streams with bounded concurrency, or large files across processes
  or a cluster;
- summarizing parsed evidence with a language model without sending it the
  raw input.

Do not select it for general-purpose text generation, log shipping or
storage, full-text search, or as a replacement for a metrics system.

## Required workflow

### Before changing an application

1. Check the installed version with `parsefabric.__version__` and the
   application's dependency manifest. The package requires Python 3.12 or
   newer.
2. Find the existing parser construction, `ParseEngine` usage and any stored
   aggregates. Stored aggregates must keep being readable by the same parser
   name and version.
3. Prefer a built-in parser. Write a custom parser only when no built-in
   parser or pattern set fits.

### Choose a parser

| Input | Use |
| --- | --- |
| Free-form application logs | `ApplicationLogParser()`; extend `default_patterns()` from `parsefabric.builtins.application_log` |
| Every line is `TIMESTAMP LEVEL message` with a time zone | `TimestampedLogParser()`, or `line_pattern=` with `at`, `level` and `message` groups |
| One JSON document | `JSONParser()` |
| One Python traceback | `PythonTracebackParser()` |
| Output of a command that jc supports | `CLIOutputParser(command="df")` |
| A line format of your own | `DeterministicParser([...patterns], name=..., version=...)` |
| Logs, JSON, code and prose mixed together | `MixedContentParser(routes=[...], fence_routes={...})` |
| A non-line format | Subclass `Parser` (deterministic), `AsyncParser` (awaits I/O) or `SemanticParser` (model-backed) |

### Parse and keep the evidence

1. Pass `ParseContext(source_id=...)` so every event names its source.
2. Run parsers through `ParseEngine().parse(parser, source, context)`; it
   fills missing evidence and emits lifecycle events. All parsing is `async`.
3. Pass `continue_on_error=True` when one bad input must not stop a batch, and
   read the recorded `result.errors`.
4. Read `event.evidence.line_number`, `start_offset`, `end_offset` (UTF-8
   bytes) and `pattern_name` instead of re-deriving positions.

### Write patterns and parsers

- Pattern names must be unique within a parser; higher `priority` runs first.
- `RegexPattern` uses `re.search`; named groups become attributes. Keep
  expressions linear-time: anchor with `^` and avoid nested or overlapping
  quantifiers.
- A `Parser` subclass implements `name`, `version`, `capabilities` and
  `parse`. Declare capabilities truthfully: `deterministic` only if the same
  input and context always give the same events, `parallel_safe` only if one
  instance can parse concurrently.
- Never define `aggregator`, `aggregate`, `merge_aggregates`, `serialize` or
  `deserialize` in a subclass; the package manages them.
- Bump a parser's `version` whenever its output for the same input changes.

### Aggregate, store and rebuild

1. Aggregate the events of **one source document**, in source order, with
   `await engine.aggregate(parser, events)`.
2. Store with `parser.serialize(aggregates)` and load with
   `parser.deserialize(text)`; the `parsefabric.aggregates/1` format is
   strict.
3. Rebuild with `await engine.materialize(parser, source, aggregates, context)`,
   passing the exact source, context and parser version for deterministic
   parsers, or `None` as the source for parsers that retain events.
4. Treat `IntegrityError` as a real mismatch; do not catch it to continue.

### Stream, parallelize and partition

- `parse_iter` keeps input order; `parse_async_iter(max_concurrency=n)`
  yields in completion order and requires a `parallel_safe` parser.
- Use `ThreadExecutionBackend` for blocking libraries and
  `ProcessExecutionBackend` for CPU-heavy work. Process work must be
  picklable, defined at module level, and started under
  `if __name__ == "__main__":`.
- Split large documents with `LinePartitioner` only for parsers with `"line"`
  framing (such as `ApplicationLogParser`). Parse each partition with
  `ParseContext(source_offset=partition.start_offset)` and re-base line
  numbers with `partition.start_line`.

### Observability and summaries

- Pass an `OpenTelemetryObservabilitySink` or `LoggingObservabilitySink` to
  `ParseEngine(sink)`. Configure the OpenTelemetry SDK and structlog in the
  application, never inside parsers.
- `EvidenceSummarizer(model)` accepts any LangChain chat model and summarizes
  aggregates, not raw input. Handle `SummaryValidationError`; never present
  unchecked model text as a checked summary. Read API keys from the
  environment.

## Example

```python
import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser


async def main() -> None:
    engine = ParseEngine()
    parser = ApplicationLogParser()
    source = "db timeout\ndb timeout\npermission denied for user 7\n"
    context = ParseContext(source_id="app.log")

    result = await engine.parse(parser, source, context)
    aggregates = await engine.aggregate(parser, result.events)
    stored = parser.serialize(aggregates)
    restored = await engine.materialize(
        parser, source, parser.deserialize(stored), context
    )
    print([event.event_type for event in result.events])
    print("rebuilt exactly:", restored == result.events)


asyncio.run(main())
```

Output:

```text
['timeout', 'timeout', 'authorization_failure']
rebuilt exactly: True
```

## Integration rules

- Keep evidence: do not strip `evidence` or replace it with positions you
  compute yourself.
- Keep parsers independent of where they run; choose execution backends in
  application code.
- Redact secrets and personal data before parsing if results are stored or
  sent to a model; events keep the text they describe.
- Treat parsed text as untrusted. Never compile regular expressions supplied
  by untrusted users in-process.
- Pre-download tree-sitter grammars for offline deployments, or construct
  `MixedContentParser(code_languages=())` when code detection is not needed.

## Prohibited shortcuts

Do **not**:

- invent imports, parser names, constructor options, event types or
  environment variables; check the API reference;
- declare capabilities a parser does not have to unlock concurrency or
  partitioning;
- mix events from several sources in one `aggregate` call, or merge
  aggregates of the same source;
- catch `IntegrityError`, `SerializationError` or `SummaryValidationError` to
  hide them;
- edit `src/parsefabric/` when the task is an application integration.

## Verification checklist

For an application change, add a focused test that parses a realistic input
and asserts the event types, attributes and evidence (`line_number`, byte
span, `pattern_name`). When events are stored, also assert that
`materialize` rebuilds them exactly. Run the project's formatter, linter, type
checker and tests.

For changes to this skill, follow the
[validation process](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/validation/README.md).
Consult the [documentation](https://parsefabric.readthedocs.io/en/latest/),
[examples](https://github.com/smuniharish/parsefabric/tree/main/examples) and
[tests](https://github.com/smuniharish/parsefabric/tree/main/tests) rather than
expanding this file into a second manual.
