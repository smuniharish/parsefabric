# Examples

Every example below is a short, runnable script from the
[`examples/`](https://github.com/smuniharish/parsefabric/tree/main/examples)
directory. The output shown is the recorded output that the test suite checks
on every change, so what you see here is what the code prints.

To run them, clone the repository and use [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run python examples/quickstart.py
```

Outside a checkout, `pip install parsefabric` is enough for every offline
example except the SQL ones, which also need `sqlglot`.

## Getting started

### Quickstart

Parse one log line and read each event's evidence.

=== "quickstart.py"

    ```python
    --8<--
    examples/quickstart.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/quickstart.txt"
    ```

### Built-in parsers

JSON, Python tracebacks, command output through jc, and timestamped logs.

=== "builtin_parsers.py"

    ```python
    --8<--
    examples/builtin_parsers.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/builtin_parsers.txt"
    ```

### Custom patterns

Build a parser from regex, exact-value and predicate patterns.

=== "custom_patterns.py"

    ```python
    --8<--
    examples/custom_patterns.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/custom_patterns.txt"
    ```

### Custom parser

An application-defined parser, the registry and retained-event aggregation.

=== "custom_parser.py"

    ```python
    --8<--
    examples/custom_parser.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/custom_parser.txt"
    ```

## Documents and evidence

### Mixed content

Route a mixed document to existing parsers, with fence routing and code
detection.

=== "mixed_content.py"

    ```python
    --8<--
    examples/mixed_content.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/mixed_content.txt"
    ```

### Aggregation

Lossless aggregation, the wire format, materialization and compression.

=== "aggregation.py"

    ```python
    --8<--
    examples/aggregation.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/aggregation.txt"
    ```

### SQL statements

A SQLGlot statement parser with grouped, lossless evidence. Requires
`sqlglot`.

=== "custom_sql.py"

    ```python
    --8<--
    examples/custom_sql.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/custom_sql.txt"
    ```

### Custom and built-in parsers together

The SQL parser routed alongside built-in parsers over three mixed files.
Requires `sqlglot`.

=== "mixed_custom_and_builtin.py"

    ```python
    --8<--
    examples/mixed_custom_and_builtin.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/mixed_custom_and_builtin.txt"
    ```

## Running at scale

### Streaming

Incremental and concurrent parsing with tolerated failures.

=== "streaming.py"

    ```python
    --8<--
    examples/streaming.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/streaming.txt"
    ```

### Execution backends

The same parser on the event loop, threads, processes and a custom backend.

=== "execution_backends.py"

    ```python
    --8<--
    examples/execution_backends.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/execution_backends.txt"
    ```

### Partitioning

Partition a large log, parse it in processes and verify parity with parsing
the whole document.

=== "partitioning.py"

    ```python
    --8<--
    examples/partitioning.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/partitioning.txt"
    ```

### Observability

Lifecycle events as OpenTelemetry spans and structlog records.

=== "observability.py"

    ```python
    --8<--
    examples/observability.py
    --8<--
    ```

=== "Output"

    ```text
    --8<-- "examples/expected/observability.txt"
    ```

## Language models

These examples call a model that you configure through environment variables.
The summarizer only ever receives aggregates, never the raw input. See
[Evidence summaries](guide/summaries.md).

| Example | Shows |
| --- | --- |
| [`llm_summary.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/llm_summary.py) | Summarize aggregates with any LangChain chat model |
| [`llm_summary_openai_compatible.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/llm_summary_openai_compatible.py) | The same with an OpenAI-compatible endpoint |
| [`semantic_llm.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/semantic_llm.py) | A `SemanticParser` that asks a model to interpret text, with a checked summary |

## Interactive playground

[`streamlit_app.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/streamlit_app.py)
lets you paste input, choose a parser, and inspect events, evidence and
aggregates in the browser:

```bash
uv run streamlit run examples/streamlit_app.py --server.address 127.0.0.1
```

## Distributed runtimes

The [integration examples](guide/distributed-runtimes.md) run the same
parsers on Celery, Apache Spark and Apache Flink with Docker Compose.
