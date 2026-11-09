# The parsefabric skill

The [`parsefabric`](https://github.com/smuniharish/parsefabric/tree/main/parsefabric-skills/skills/parsefabric) skill guides an agent that uses
ParseFabric in an application. It loads for tasks such as "parse these
service logs and keep line evidence" or "store these events and rebuild them
exactly", and stays out of the way for log shipping, full-text search or
metrics.

## What it teaches

- Checking the installation first with `scripts/verify_setup.py`.
- Choosing a built-in parser, adding patterns, and routing mixed documents.
- Parsing with `ParseEngine`, collecting errors with `continue_on_error`, and
  keeping line and byte-span evidence.
- Aggregating one source at a time, serializing, and proving that
  `materialize` rebuilds every event.
- Streaming, partitioning and execution backends for large inputs and
  clusters.
- OpenTelemetry and structlog sinks, and checked language-model summaries.
- Diagnosing an `IntegrityError`, missing events or wrong line numbers.

## Files

| File | Read or run it when |
| --- | --- |
| [`SKILL.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/SKILL.md) | Always: the workflow, rules and gotchas. |
| [`references/parsers.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/references/parsers.md) | Choosing or configuring a parser. |
| [`references/storage.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/references/storage.md) | Storing and rebuilding events. |
| [`references/execution.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/references/execution.md) | Streaming, partitioning or distributing work. |
| [`references/observability.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/references/observability.md) | Sending lifecycle events to telemetry. |
| [`references/summaries.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/references/summaries.md) | Summarizing evidence with a language model. |
| [`references/troubleshooting.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/references/troubleshooting.md) | Something fails or looks wrong. |
| [`scripts/verify_setup.py`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/scripts/verify_setup.py) | Before changing code: checks versions, then parses, stores and rebuilds a sample offline. |
| [`assets/test_parsing.py`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric/assets/test_parsing.py) | A test to copy that proves evidence and a lossless round trip. |

## Check an installation

```bash
python scripts/verify_setup.py              # human-readable
python scripts/verify_setup.py --langchain  # also require the LangChain integration
python scripts/verify_setup.py --json       # machine-readable
```

The script exits with code 0 when every check passes and 1 otherwise.
