---
name: parsefabric
description: >-
  Use this skill when an application parses operational text with ParseFabric
  (the parsefabric package): application or timestamped logs, JSON documents,
  Python tracebacks, command output such as df, or documents that mix logs,
  JSON, code and prose. That includes keeping line and byte-span evidence for
  every event, storing events as compact checksummed aggregates and rebuilding
  them exactly, streaming or partitioning parsing across threads, processes or
  a cluster, sending lifecycle events to OpenTelemetry or structlog, writing
  checked language-model summaries of parsed evidence, and debugging an
  IntegrityError, missing events or wrong line numbers. Do not use it to
  subclass a ParseFabric abstract base class (a custom Parser, Pattern,
  Aggregator, codec, partitioner, execution backend, sink, language model,
  tokenizer, code detector, command output backend or registry); the
  parsefabric-extend skill covers those. Do not use it for log shipping,
  full-text search or metrics.
license: Apache-2.0
compatibility: >-
  Python 3.12 or newer with parsefabric 1.x installed (pip install
  parsefabric). The scripts run offline; the langchain extra is optional.
metadata:
  version: "1.0.0"
  documentation: "https://parsefabric.readthedocs.io/en/latest/"
---

# Using ParseFabric

ParseFabric turns operational text into `ParsedEvent`s. Each event records
its source, line, UTF-8 byte span, pattern and parser version. Aggregates
store repetitive events compactly and rebuild them exactly. Everything that
does work is `async`.

```python
from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser, MixedContentParser
from parsefabric.patterns import RegexPattern
```

## Workflow

1. Run `python scripts/verify_setup.py` (add `--langchain` when the project
   uses the LangChain integration). Fix every FAIL before you change code.
2. Find the existing `ParseEngine` usage, parser construction and any stored
   aggregates. Stored aggregates are rebuilt by the same parser name and
   version, so never change a parser's output without bumping its version.
3. Choose a built-in parser from the table below. Read
   [references/parsers.md](references/parsers.md) for patterns, routes, fence
   routes and command output. If no built-in parser fits, switch to the
   parsefabric-extend skill.
4. Parse with `await ParseEngine().parse(parser, source, ParseContext(source_id=...))`.
   Pass `continue_on_error=True` when one bad input must not stop a batch,
   and read `result.errors`.
5. To store events, aggregate one source document at a time, serialize, and
   prove that `materialize` rebuilds them. Read
   [references/storage.md](references/storage.md).
6. For many inputs, large files, or clusters, read
   [references/execution.md](references/execution.md). For telemetry, read
   [references/observability.md](references/observability.md). For model
   summaries, read [references/summaries.md](references/summaries.md).
7. Copy `assets/test_parsing.py` into the project's tests, point it at the
   real parser and a realistic input, and make it pass.
8. Run `python scripts/verify_setup.py` again, then the project's own tests.
   Do not finish until both pass.

## Choose a parser

| Input | Use |
| --- | --- |
| Free-form application logs | `ApplicationLogParser()`; extend `default_patterns()` from `parsefabric.builtins.application_log` |
| Lines of `TIMESTAMP LEVEL message` with a time zone | `TimestampedLogParser()`, or `line_pattern=` with `at`, `level` and `message` groups |
| One JSON document | `JSONParser()` |
| One Python traceback | `PythonTracebackParser()` |
| Output of a command jc supports | `CLIOutputParser(command="df")` |
| A line format of your own | `DeterministicParser([...patterns], name=..., version=...)` |
| Logs, JSON, code and prose together | `MixedContentParser(routes=[...], fence_routes={...})` |

## Rules

- Keep evidence. Read `event.evidence.line_number`, `start_offset`,
  `end_offset` and `pattern_name`; never recompute positions yourself.
- Aggregate the events of **one** source document, in source order. Combine
  aggregates of different documents only with `engine.merge_aggregates`.
- Treat `IntegrityError` as a real mismatch between the stored aggregates and
  the source, context or parser version. Never catch it to carry on.
- Declare nothing you have not verified: concurrency needs a
  `parallel_safe` parser, partitioning needs `"line"` framing.
- Keep parsers independent of where they run. Choose execution backends,
  sinks and models in application code and pass them in.
- Redact secrets and personal data before parsing when results are stored or
  sent to a model; events keep the text they describe.
- Never compile regular expressions supplied by untrusted users.
- Configure OpenTelemetry, structlog and model providers in the
  application. ParseFabric never configures them and has no global registry.

## Gotchas

- `ParseEngine.parse` is a coroutine. Calling it without `await` returns a
  coroutine, not a result.
- One input line can produce several events. `ApplicationLogParser` reports
  `timeout` and `error` for "ERROR payment gateway timed out".
- `EvidenceAggregator` keeps one entry per distinct message within each
  pattern and severity, with every position in source order. Repeats far
  apart still share one entry.
- `materialize` for a deterministic parser needs the exact source, context
  and parser version used to parse. Pass `None` as the source only for
  parsers whose aggregator retains events.
- `parse_async_iter(max_concurrency=n)` yields in completion order;
  `parse_iter` keeps input order.
- `ProcessExecutionBackend` needs picklable, module-level callables and an
  `if __name__ == "__main__":` guard.
- `MixedContentParser` downloads tree-sitter grammars on first use. For
  offline deployments, run `await TreeSitterCodeDetector().prepare()` while
  building the image, or pass `code_detector=None`.

## Checklist before you finish

- [ ] `scripts/verify_setup.py` passes after the change.
- [ ] A test asserts event types, attributes and evidence for a realistic input.
- [ ] When events are stored, a test asserts that `materialize` rebuilds them exactly.
- [ ] No `IntegrityError`, `SerializationError` or `SummaryValidationError` is silenced.
- [ ] The project's formatter, linter, type checker and tests pass.

## Files

- `scripts/verify_setup.py`: checks Python, ParseFabric and its dependency
  ranges, then parses, stores and rebuilds a sample offline. Run `--help`
  for options; `--json` prints one object. Exit codes are 0 (all pass) and
  1 (a check failed).
- `assets/test_parsing.py`: tests to copy into the project. They assert
  evidence, a lossless round trip, and that a changed source is rejected.
- [references/parsers.md](references/parsers.md): built-in parsers,
  patterns, mixed content and command output.
- [references/storage.md](references/storage.md): aggregation, the stored
  format, rebuilding, and measuring the reduction.
- [references/execution.md](references/execution.md): streaming, execution
  backends, partitioning and distributed runtimes.
- [references/observability.md](references/observability.md): lifecycle
  events, OpenTelemetry and structlog.
- [references/summaries.md](references/summaries.md): checked summaries,
  language models and LangChain.
- [references/troubleshooting.md](references/troubleshooting.md): symptoms,
  causes and fixes.
