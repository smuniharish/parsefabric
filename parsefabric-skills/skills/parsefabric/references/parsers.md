# Parsers, patterns and mixed content

Read this when choosing or configuring a built-in parser. The full guide is
[Built-in parsers](https://parsefabric.readthedocs.io/en/latest/guide/builtin-parsers/)
and [Patterns and custom parsers](https://parsefabric.readthedocs.io/en/latest/guide/custom-parsers/).

## Built-in parsers

All are in `parsefabric.builtins`.

| Parser | Input | Events |
| --- | --- | --- |
| `ApplicationLogParser()` | Free-form log lines | `service_down`, `connection_failure`, `authentication_failure`, `authorization_failure`, `timeout`, `oom`, `retry`, `stack_trace`, `error`, `warning` |
| `TimestampedLogParser()` | `TIMESTAMP LEVEL message` lines with a time zone | `log`, with `at`, `level` and `message` attributes |
| `JSONParser()` | One JSON document | `json_record` with the document as `value`; invalid JSON gives `unparsed` and a `ParseIssue` |
| `PythonTracebackParser()` | One Python traceback | One `python_exception` with `exception_type`, `message` and `frames` |
| `CLIOutputParser(command="df")` | Output of a command jc supports | One `cli_record` per record |
| `DeterministicParser(patterns, name=..., version=...)` | Lines matching your patterns | One event per matching pattern, or the first only with `first_match_only=True` |
| `MixedContentParser(...)` | Logs, JSON, code and prose together | Routed parsers' events, plus `code`, `fence` and `other` |

- `ApplicationLogParser` runs every pattern on every line, so one line can
  produce several events. To add a pattern, pass
  `[*default_patterns(), RegexPattern(...)]` from
  `parsefabric.builtins.application_log`.
- `TimestampedLogParser(line_pattern=...)` accepts a regular expression with
  `at`, `level` and `message` named groups. A line that does not match, or a
  timestamp without a time zone, raises `ParseError` naming the line.
- `CLIOutputParser` lists its commands with
  `python -c "import jc; print(jc.parser_mod_list())"`. Streaming jc parsers
  (names ending in `_s`) are not supported.

## Patterns

All are in `parsefabric.patterns`.

| Pattern | Matches | Attributes |
| --- | --- | --- |
| `RegexPattern(name, expression)` | Text the expression finds anywhere (`re.search`) | The named groups that matched |
| `ExactPattern(name, expected)` | Values equal to `expected` | The fixed `attributes` you supply |
| `PredicatePattern(name, predicate, extractor)` | Values where `predicate(value)` is true | `extractor(value)`, or none |
| `StructuredPattern(name, predicate, extractor)` | Mappings where `predicate` is true | `extractor(mapping)`, or the mapping |

- Names are unique within a parser; a higher `priority` is tried first.
- Keep expressions linear-time: anchor with `^`, and avoid nested or
  overlapping quantifiers such as `(a+)+`.
- Every pattern accepts a `severity` for the events it produces.
- `DeterministicParser` is deterministic, parallel-safe and
  line-partitionable by default. If a `PredicatePattern` callable is not
  thread-safe, pass explicit `capabilities` without `parallel_safe`.

## Mixed content

```python
from parsefabric.builtins import JSONParser, MixedContentParser, TimestampedLogParser
from parsefabric.patterns import RegexPattern

json_parser = JSONParser()
parser = MixedContentParser(
    routes=[
        (RegexPattern("log-line", r"^\d{4}-\d\d-\d\dT"), TimestampedLogParser()),
        (RegexPattern("json-line", r"^\{"), json_parser),
    ],
    fence_routes={"json": json_parser},
)
```

Each line is handled by the first rule that applies:

1. **Fences.** A fenced block's body goes to the parser in `fence_routes` for
   its language tag; otherwise every body line becomes a `code` event. The
   marker lines become `fence` events.
2. **Routes.** The first matching selector sends the line to its parser. A
   route to `JSONParser` continues until the JSON value is complete. If the
   routed parser returns no events, the next route is tried.
3. **Patterns.** The first matching line pattern produces an event. The
   default `log-level` pattern recognizes `LEVEL message` lines.
4. **Code and text.** Blocks that a tree-sitter grammar parses become `code`
   events with a `language`; everything else becomes `other`.

Rules:

- Selectors identify a format cheaply; the routed parser does the real work
  and keeps its own name, version and evidence.
- Pattern and selector names are unique; `code`, `code_fence` and `other`
  are reserved. Routed parsers that share a name must be the same instance.
- The parser is never partitionable, because fences, code blocks and JSON
  span lines.
- Grammars are downloaded on first use. For offline deployments, run
  `await TreeSitterCodeDetector(languages).prepare()` while building the
  image, or pass `code_detector=None`.
