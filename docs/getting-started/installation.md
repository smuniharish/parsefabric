# Installation

## Requirements

ParseFabric supports **Python 3.12, 3.13 and 3.14** on Linux, macOS and
Windows. It is a pure-Python package; its dependencies ship prebuilt wheels
for all three platforms.

## Install the package

=== "pip"

    ```bash
    pip install parsefabric
    ```

=== "uv"

    ```bash
    uv add parsefabric
    ```

Check the installation:

```bash
python -c "import parsefabric; print(parsefabric.__version__)"
```

## Optional extras

| Extra | Installs | Use it for |
| --- | --- | --- |
| `openai` | `langchain-openai` | [Evidence summaries](../guide/summaries.md) with OpenAI or an OpenAI-compatible endpoint |

```bash
pip install "parsefabric[openai]"
```

Evidence summaries work with any LangChain chat model. To use another
provider, install its LangChain integration package (for example
`langchain-anthropic`) instead of the extra.

## What gets installed

| Dependency | Why ParseFabric needs it |
| --- | --- |
| `msgspec` | Fast JSON decoding in `JSONParser` |
| `jc` | Command-output parsers behind `CLIOutputParser` |
| `tree-sitter`, `tree-sitter-language-pack` | Grammar-based code detection in `MixedContentParser` |
| `opentelemetry-api` | The `OpenTelemetryObservabilitySink`; the API alone records nothing until you configure an SDK |
| `structlog` | The `LoggingObservabilitySink` |
| `pydantic`, `langchain-core`, `langgraph` | Structured claims and the review workflow of `EvidenceSummarizer` |

ParseFabric never configures logging, telemetry export or a model provider
for you; your application decides where data goes.

## Export telemetry

To export lifecycle events as traces, add the OpenTelemetry SDK and an
exporter, for example OTLP over HTTP:

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
```

See [Observability](../guide/observability.md) for a complete setup.

## Code-detection grammars

Code detection uses tree-sitter grammars from `tree-sitter-language-pack`.
Grammars that are not yet on disk are **downloaded when a `CodeDetector` (or
a `MixedContentParser` with code detection) is created**, and cached in a
per-user directory. For offline or locked-down deployments, download them
ahead of time, for example while building a container image:

```bash
python -c "import tree_sitter_language_pack as t; t.download(['python', 'javascript', 'typescript', 'java', 'go', 'rust', 'c', 'cpp', 'sql'])"
```

To choose the cache directory, call
`tree_sitter_language_pack.configure(PackConfig(cache_dir=...))` before
creating a detector. To turn code detection off entirely, create the parser
with `MixedContentParser(code_languages=())`.

## Install from source

To work on ParseFabric itself, clone the repository and install every
development dependency with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/smuniharish/parsefabric.git
cd parsefabric
uv sync
```

See [Contributing](../development/contributing.md) for the full workflow.
