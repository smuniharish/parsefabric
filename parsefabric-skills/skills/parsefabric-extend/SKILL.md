---
name: parsefabric-extend
description: >-
  Use this skill when extending ParseFabric (the parsefabric package) by
  subclassing one of its abstract base classes: a custom Parser, AsyncParser
  or SemanticParser for a new input format, a Pattern, an Aggregator, an
  AggregateCodec or JSONCodec for another storage format, a Partitioner, an
  ExecutionBackend for Ray, Dask or another cluster, an ObservabilitySink for
  metrics or a message queue, a LanguageModel for a provider without LangChain,
  a ParserRegistry backed by a database, a Tokenizer, a CodeDetector or a
  CommandOutputBackend. Also use it to test such an extension with the
  parsefabric.testing contract checks or to debug one that fails them. Do not
  use it to parse, store, stream or summarize text with the built-in
  components, or to configure OpenTelemetry or LangChain; the parsefabric
  skill covers those.
license: Apache-2.0
compatibility: >-
  Python 3.12 or newer with parsefabric 1.x installed (pip install
  parsefabric). The templates and scripts run offline.
metadata:
  version: "1.0.0"
  documentation: "https://parsefabric.readthedocs.io/en/latest/extending/"
---

# Extending ParseFabric

Every replaceable part of ParseFabric is an abstract base class with a
default implementation. Subclass the ABC, implement its abstract methods, and
pass an instance to the component that uses it. There is no global registry
and no monkey-patching: what runs is what the application constructs.
`parsefabric.testing` has one contract check per ABC.

## Workflow

1. Confirm that no built-in component already fits. A line format usually
   needs only patterns in a `DeterministicParser`; the parsefabric skill
   covers that. Read [references/extension-points.md](references/extension-points.md)
   to choose the ABC, its default, and where an instance is passed.
2. For a parser, copy `assets/parser_template.py` and adapt `RECORD` and
   `to_event`. For a sink, copy `assets/sink_template.py` and replace
   `send`. For other ABCs, start from the members listed in the reference.
3. Implement every abstract method as declared: methods that may do I/O are
   coroutines. Offload blocking or CPU-bound work with `asyncio.to_thread`.
4. Copy the matching test (`assets/test_parser.py` or `assets/test_sink.py`)
   next to the extension, change the import and the sample, and run it.
5. Run `python scripts/check_extension.py MODULE:FACTORY` from the project
   root, with the inputs the script asks for. Fix the first broken promise,
   then rerun until it passes.
6. Pass the extension in through its constructor parameter and run one real
   parse.

## Rules

- Subclass the ABC; never duck-type it. ParseFabric checks types with
  `isinstance`, and an unimplemented method fails at construction.
- Declare only capabilities the parser really has. `partitionable` needs a
  deterministic, parallel-safe, stateless, order-independent parser and a
  `partition_framing`.
- Keep evidence: set `line_number`, `start_offset`, `end_offset` and
  `pattern_name` on every event, and honour `context.source_offset`.
- Bump a parser's `version` whenever its events for the same input change;
  stored aggregates are rebuilt by name and version.
- Report expected input problems as `ParseIssue`s in `ParseResult.errors`;
  raise `ParseError` only when nothing can be parsed. Never drop input
  silently.
- Sinks must not raise and must keep `emit` fast. Language models, clients
  and connections are created and closed by the application.
- Never weaken a contract check, catch `AssertionError` or skip a check to
  make an extension pass.

## Gotchas

- `ParserCapabilities` validates the combination at construction:
  `stateful` or `requires_order` together with `parallel_safe` raises
  `ValueError`.
- A deterministic, aggregatable parser's aggregates store only line
  positions, so `materialize` re-parses the source. If parsing is not
  repeatable, declare `deterministic=False`.
- Override `build_aggregator`, not `aggregator`: the property caches one
  instance per parser.
- `ProcessExecutionBackend` and cluster backends need module-level,
  picklable callables. `check_execution_backend` sends functions from
  `parsefabric.testing`, so workers must be able to import ParseFabric.
- `check_language_model` calls the model once: a live model needs its
  credentials, and a test should use a fake model.
- `Pattern.match` stays synchronous: it runs once per line on the hot path.

## Checklist before you finish

- [ ] `scripts/check_extension.py` passes for the extension.
- [ ] The copied tests pass, with a realistic sample.
- [ ] The extension is injected through a constructor, not a global.
- [ ] The project's formatter, linter, type checker and tests pass.

## Files

- `assets/parser_template.py` and `assets/test_parser.py`: a line-record
  parser with evidence, issues and partitioning, and its tests.
- `assets/sink_template.py` and `assets/test_sink.py`: a batching
  observability sink, and its tests.
- `scripts/check_extension.py`: detects which ABC an extension subclasses
  and runs its contract check without pytest. Run `--help` for the inputs
  each extension point needs; `--json` prints one object. Exit codes are 0
  (the contract holds), 1 (a promise is broken) and 2 (not loadable, not an
  extension, or an input is missing).
- [references/extension-points.md](references/extension-points.md): every
  ABC, its members, default, injection point and contract check.
- [references/parsers-and-aggregators.md](references/parsers-and-aggregators.md):
  capabilities, evidence, versions, aggregators and codecs.
- [references/runtime-components.md](references/runtime-components.md):
  execution backends, partitioners, sinks, language models, registries,
  tokenizers, code detectors and command output backends.
