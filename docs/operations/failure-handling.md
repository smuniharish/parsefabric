# Failure handling

ParseFabric reports failures explicitly. Nothing is retried, dropped or
approved silently: a failure either raises an exception or is recorded in the
result, depending on what you ask for.

## Parsing

- Parser exceptions propagate by default. With `continue_on_error=True`, the
  engine records the failure as a `ParseIssue` in the result's `errors` and
  emits a `ParseFailed` lifecycle event, so one bad input does not stop a
  stream.
- Cancellation always propagates; it is never converted into a parse issue.
- Some parsers record expected problems themselves. `JSONParser` and
  `CLIOutputParser` return an `unparsed` event plus a `ParseIssue` for input
  they cannot decode, and `CLIOutputParser` warns when jc finds no records in
  non-blank output. `TimestampedLogParser` raises `ParseError` naming the
  first line that is not a valid record.
- `MixedContentParser` falls back instead of failing: a fenced block that its
  parser rejects is kept as `code` events, and lines that nothing claims
  become `other` events.
- ParseFabric never retries a parse. Parsers can have side effects and a
  stream may not be replayable, so retry policy belongs to your application.

## Streams and execution

- Closing or cancelling a `parse_async_iter` stream cancels the outstanding
  parses and waits for them to settle.
- `ExecutionBackend.map` raises the first failure and cancels the remaining
  calls.
- Python cannot interrupt work that is already running in a thread or a
  process. Cancelling stops waiting for it, and `shutdown` waits for it to
  finish. Shutdown is idempotent.
- If a process worker dies, `ProcessExecutionBackend` raises
  `BrokenProcessPool` and refuses further work. It does not restart workers or
  resubmit work: shut it down, create a new backend, and decide whether the
  work is safe to repeat.

## Aggregation and storage

| Situation | Result |
| --- | --- |
| Events from more than one source, out of source order, or from two versions of one parser | `ValueError` from `aggregate` |
| A stored document that is malformed, has unknown or missing fields, or has inconsistent counts | `SerializationError` from `deserialize` or `loads_result` |
| Source, context or parser version that does not reproduce the aggregates | `IntegrityError` from `materialize` |
| Merging two aggregates of the same source document | `CapabilityError` from `merge_aggregates` |

## Evidence summaries

- Drafts and critiques must match strict schemas. Output that does not parse
  counts as a failed review, never as approval, and uses the same revision
  budget as a rejected claim.
- A batch that still fails after `max_revisions` repairs raises
  `SummaryValidationError`.
- Summarizing an empty set of aggregates raises `ValueError`.

## Exceptions

Every ParseFabric exception derives from `ParseFabricError`, so one `except`
clause can catch them all. Exceptions that signal invalid values also derive
from `ValueError`.

| Exception | Raised when |
| --- | --- |
| `ParseError` | A parser cannot interpret its input |
| `ConfigurationError` | A parser or runtime configuration is invalid |
| `CapabilityError` | An operation conflicts with a parser's declared capabilities |
| `SerializationError` | A value cannot be encoded to, or decoded from, a supported JSON format |
| `IntegrityError` | Aggregates cannot be materialized into verified original events |
| `RegistryError` | A registry operation is invalid |
| `DuplicateParserError` | A parser name is already registered |
| `SummaryValidationError` | A language-model summary did not pass review |
