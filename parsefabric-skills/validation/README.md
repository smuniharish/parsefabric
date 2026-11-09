# Validating the ParseFabric skills

The `parsefabric` and `parsefabric-extend` skills are validated in three
ways: automated checks on every change, evaluations against real tasks, and a
review of every claim against its source.

## Automated checks

Run from the repository root:

```bash
uv run pytest tests/skill
uvx --from skills-ref agentskills validate parsefabric-skills/skills/parsefabric
uvx --from skills-ref agentskills validate parsefabric-skills/skills/parsefabric-extend
```

`tests/skill` runs offline in continuous integration. For both skills it
checks that:

- the frontmatter passes `skills-ref`. `name` matches the directory, the
  description starts with "Use this skill when", `license` is `Apache-2.0`,
  and `metadata.version` equals the package version;
- `SKILL.md` has fewer than 500 lines and links every reference;
  `references/` is one level deep, and every relative link resolves;
- `SKILL.md` mentions every bundled script and asset;
- `evals/evals.json` and `evals/trigger_queries.json` are well formed. The
  trigger queries are balanced, split into training and validation sets, and
  no query triggers both skills;
- the skills CLI discovers both skills through `skills.sh.json`.

It also runs the bundled code:

- `parsefabric/scripts/verify_setup.py` passes, with warnings treated as
  errors, prints valid JSON with `--json`, and requires the package's
  dependency ranges;
- `parsefabric/assets/test_parsing.py` passes;
- the `parsefabric-extend` parser and sink templates pass their tests;
- `parsefabric-extend/scripts/check_extension.py` handles four cases:
    - it passes conforming extensions of every kind it detects;
    - it names the promise a broken extension violates, with exit code 1;
    - it exits with code 2 when a required input is missing;
    - it exits with code 2 for a factory it can't load.

`tests/integration/test_docs.py` also compiles every Python snippet in the
skills and checks every link. CI runs `verify_setup.py --langchain` and
`check_extension.py` against the built wheel.

## Evaluations

Each skill has an `evals/` folder, in the format described in
[Evaluating skills](https://agentskills.io/skill-creation/evaluating-skills):

- `evals.json`: realistic tasks with input files, an expected result, and
  assertions a grader can verify.
- `trigger_queries.json`: 10 requests that should load the skill and 10 near
  misses that shouldn't, split 12/8 into training and validation.

To evaluate a change:

1. Copy each task's input files into fresh workspaces, one with the skill and
   one without.
2. Run each task in a new agent session. The session without the skill can
   read the installed package but not the skill, the docs, or the
   repository's source.
3. Grade every assertion as passed or failed, with the evidence. Record time
   and tool calls.
4. Compare the two variants. Change the skill where the agent went wrong with
   it, or where it did no better than without it, then run the evaluation
   again.

Keep workspaces and benchmark files out of the repository.

## Source review

Automated checks can't tell whether guidance is correct. For every change,
check each snippet and claim against its source:

| Claim area | Source of truth |
| --- | --- |
| Public imports and the package version | [`src/parsefabric/__init__.py`](../../src/parsefabric/__init__.py) and [`pyproject.toml`](../../pyproject.toml) |
| Engine, streaming and evidence | [`src/parsefabric/engine.py`](../../src/parsefabric/engine.py) and [`src/parsefabric/models.py`](../../src/parsefabric/models.py) |
| Parser contract and capabilities | [`src/parsefabric/parser/`](../../src/parsefabric/parser/) and [`src/parsefabric/capabilities.py`](../../src/parsefabric/capabilities.py) |
| Built-in parsers | [`src/parsefabric/builtins/`](../../src/parsefabric/builtins/) |
| Aggregation and the stored format | [`src/parsefabric/aggregation/`](../../src/parsefabric/aggregation/) and [`src/parsefabric/codecs.py`](../../src/parsefabric/codecs.py) |
| Execution and partitioning | [`src/parsefabric/execution/`](../../src/parsefabric/execution/) and [`src/parsefabric/partitioning.py`](../../src/parsefabric/partitioning.py) |
| Observability | [`src/parsefabric/observability.py`](../../src/parsefabric/observability.py) |
| Summaries, language models and LangChain | [`src/parsefabric/summarization.py`](../../src/parsefabric/summarization.py), [`src/parsefabric/llm.py`](../../src/parsefabric/llm.py) and [`src/parsefabric/integrations/`](../../src/parsefabric/integrations/) |
| Contract checks | [`src/parsefabric/testing.py`](../../src/parsefabric/testing.py) and the [extending guide](../../docs/extending/index.md) |
| Working patterns | [`examples/`](../../examples/) and [`tests/`](../../tests/) |

If a behavior has no implementation, test or documentation, leave it out of
the skill rather than infer it.

## Routing matrix

Check that the descriptions send each task to the right skill:

| Task | Skill | Route | Avoids |
| --- | --- | --- | --- |
| "Extract errors and timeouts from our service logs." | `parsefabric` | `ApplicationLogParser` with a `ParseContext` and the engine | Hand-written line splitting without evidence |
| "Our logs have a custom line format; parse them." | `parsefabric` | `DeterministicParser` with `RegexPattern`s, or `TimestampedLogParser(line_pattern=...)` | Non-linear regular expressions |
| "Store parsed events compactly and restore them later." | `parsefabric` | `aggregate`, `serialize`, `deserialize` and `materialize` with the exact source | Merging aggregates of one source or catching `IntegrityError` |
| "Parse a 10 GB log faster." | `parsefabric` | `LinePartitioner` with `ProcessExecutionBackend` and line re-basing | Declaring false capabilities to unlock partitioning |
| "Summarize this incident log with GPT." | `parsefabric` | `EvidenceSummarizer` over aggregates with a `LanguageModel` | Sending raw logs to the model or returning unchecked text |
| "Parse our binary audit format." | `parsefabric-extend` | The parser template, its tests and `check_extension.py` | Claiming capabilities the parser lacks |
| "Run parsefabric on our Ray cluster." | `parsefabric-extend` | An `ExecutionBackend` subclass checked by `check_execution_backend` | Blocking the event loop in `run` |
| "Write a chatbot that answers questions about our logs." | Neither | Not this package's purpose | Inventing conversational APIs |
