# ParseFabric examples

Each example is a short, runnable script. The offline ones print
deterministic output that is recorded in [`expected/`](expected/) and checked
by [`verify_examples.py`](verify_examples.py); the documentation shows the
same files.

From a checkout, install everything the examples use with `uv sync`, then run
any example with `uv run python examples/<name>.py`.

## Offline examples

| Example | Shows |
| --- | --- |
| [`quickstart.py`](quickstart.py) | Parse one log line and read each event's evidence |
| [`custom_patterns.py`](custom_patterns.py) | Build a parser from regex, exact-value and predicate patterns |
| [`builtin_parsers.py`](builtin_parsers.py) | JSON, Python tracebacks, command output (jc) and timestamped logs |
| [`mixed_content.py`](mixed_content.py) | Route a mixed document to existing parsers, with code and fence detection |
| [`aggregation.py`](aggregation.py) | Lossless aggregation, the wire format, materialization and compression |
| [`streaming.py`](streaming.py) | Incremental and concurrent parsing with tolerated failures |
| [`execution_backends.py`](execution_backends.py) | The same parser on the event loop, threads, processes and a custom backend |
| [`partitioning.py`](partitioning.py) | Partition a large log, parse it in processes and verify parity |
| [`custom_parser.py`](custom_parser.py) | An application-defined parser, the registry and retained-event aggregation |
| [`observability.py`](observability.py) | Lifecycle events as OpenTelemetry spans and structlog records |
| [`custom_sql.py`](custom_sql.py) | A SQLGlot statement parser with grouped, lossless evidence (needs `sqlglot`) |
| [`mixed_custom_and_builtin.py`](mixed_custom_and_builtin.py) | The SQL parser routed alongside built-in parsers over three files (needs `sqlglot`) |

Check that every offline example still prints its recorded output:

```bash
uv run python examples/verify_examples.py
```

After an intended change, record the new output with `--update` and review
the diff.

## Language-model examples

These call a model you configure through environment variables; they never
send the raw input to the summarizer.

| Example | Shows |
| --- | --- |
| [`llm_summary.py`](llm_summary.py) | Summarize aggregates with any LangChain chat model (`PARSEFABRIC_LLM_MODEL`) |
| [`llm_summary_openai_compatible.py`](llm_summary_openai_compatible.py) | The same with an OpenAI-compatible endpoint (`PARSEFABRIC_LLM_API_KEY`, `PARSEFABRIC_LLM_BASE_URL`, `PARSEFABRIC_LLM_MODEL`) |
| [`semantic_llm.py`](semantic_llm.py) | A `SemanticParser` that asks a model to interpret text, with an evidence-checked summary |

## Interactive playground

[`streamlit_app.py`](streamlit_app.py) (with [`ui_backend.py`](ui_backend.py))
lets you paste input, pick a parser and inspect events, evidence and
aggregates:

```bash
uv run streamlit run examples/streamlit_app.py --server.address 127.0.0.1
```

## Distributed runtimes

[`integrations/`](integrations/) runs the same parsers on Celery, Apache
Spark and Apache Flink with Docker Compose.

## Data

[`data/`](data/) holds the fictional inputs used by the examples and tests.
[`generate_mixed_log.py`](generate_mixed_log.py) regenerates
`data/incident-mixed.log`.
