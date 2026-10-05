# parsefabric Agent Skill validation

This directory documents how the canonical skill is validated. It is not a
second test suite for the library.

The [Agent Skills specification](https://agentskills.io/specification)
defines the required frontmatter. Validation combines automated structural
checks with a review of every claim against its source.

## Automated checks

`tests/integration/test_agent_skill.py` runs with the test suite and checks
that:

1. [`../skills/parsefabric/SKILL.md`](../skills/parsefabric/SKILL.md) exists
   and starts with YAML frontmatter that contains only `name` and
   `description`.
2. `name` is exactly `parsefabric`, the directory name, and satisfies the
   specification: 1 to 64 lowercase letters, digits and single hyphens, not
   starting or ending with a hyphen.
3. `description` is 1 to 1,024 characters long and says both what the skill
   does and when to use it.
4. The skill body stays under 500 lines, as the specification recommends.
5. Every relative link in this distribution resolves to an existing file, and
   every absolute link to the repository points to a path that exists.
6. The distribution contains exactly one skill directory.

`tests/integration/test_docs.py` also runs the Python example in `SKILL.md`
and compares its output with the documented output.

The reference validator from the specification gives an independent check. It
is installed from its repository:

```bash
uvx --from "git+https://github.com/agentskills/agentskills#subdirectory=skills-ref" \
  skills-ref validate parsefabric-skills/skills/parsefabric
```

## Source review

Review every code snippet and factual claim against its source:

| Claim area | Source of truth |
| --- | --- |
| Public imports and version | [`src/parsefabric/__init__.py`](../../src/parsefabric/__init__.py) and [`pyproject.toml`](../../pyproject.toml) |
| Engine, streaming and evidence completion | [`src/parsefabric/engine.py`](../../src/parsefabric/engine.py) |
| Parser contract and capabilities | [`src/parsefabric/parser/`](../../src/parsefabric/parser/) and [`src/parsefabric/capabilities.py`](../../src/parsefabric/capabilities.py) |
| Built-in parsers | [`src/parsefabric/builtins/`](../../src/parsefabric/builtins/) |
| Aggregation and the wire format | [`src/parsefabric/aggregation/`](../../src/parsefabric/aggregation/) |
| Execution and partitioning | [`src/parsefabric/execution/`](../../src/parsefabric/execution/) and [`src/parsefabric/partitioning.py`](../../src/parsefabric/partitioning.py) |
| Summaries | [`src/parsefabric/summarization.py`](../../src/parsefabric/summarization.py) |
| Executable workflows | [`examples/`](../../examples/) and [`tests/`](../../tests/) |

If a behavior has no implementation, test or documentation, leave it out of
the skill rather than infer an API.

## Agent-task matrix

Review the skill against these tasks after every change:

| Task | Activates | Grounded route | Avoids |
| --- | --- | --- | --- |
| "Extract errors and timeouts from our service logs." | Yes | `ApplicationLogParser` with a `ParseContext` and the engine | Hand-written line splitting without evidence |
| "Our logs have a custom format; parse them." | Yes | `DeterministicParser` with `RegexPattern`s, or `TimestampedLogParser(line_pattern=...)` | Non-linear regular expressions |
| "Parse incident notes that mix logs, JSON and code." | Yes | `MixedContentParser` with routes and fence routes | Guessing fenced content without a language tag |
| "Store parsed events compactly and restore them later." | Yes | `aggregate`, `serialize`, `deserialize` and `materialize` with the exact source | Merging aggregates of one source or catching `IntegrityError` |
| "Parse a 10 GB log faster." | Yes | `LinePartitioner` with `ProcessExecutionBackend` and line re-basing | Declaring false capabilities to unlock partitioning |
| "Send parse telemetry to our OpenTelemetry collector." | Yes | `OpenTelemetryObservabilitySink` with an application-configured SDK | Configuring telemetry inside a parser |
| "Summarize this incident log with GPT." | Yes | `EvidenceSummarizer` over aggregates with a LangChain model | Sending raw logs to the model or returning unchecked text |
| "Write a chatbot that answers questions about our logs." | No | Explain that ParseFabric parses and summarizes evidence; it is not a chat framework | Inventing conversational APIs |

## Repository checks

Skill-only changes should pass the automated checks above and a review of the
diff. If library code changes too, run the checks in
[CONTRIBUTING.md](../../CONTRIBUTING.md).
