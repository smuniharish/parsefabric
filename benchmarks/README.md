# Benchmarks and soak tests

These scripts measure ParseFabric on the machine that runs them. They are
diagnostics for spotting regressions, not performance guarantees. Run them
from the repository root as modules:

| Command | Measures |
| --- | --- |
| `uv run python -m benchmarks.bench_parse --scale small` | Wall time, CPU and traced memory for parsing, streaming, partitioning, aggregation, serialization and each execution backend |
| `uv run python -m benchmarks.throughput_gate --backend process` | Repeated throughput samples for one backend; fails below the configured minimum rate |
| `uv run python -m benchmarks.resilience_load` | Sustained load across the async, thread and process backends with exact fingerprints and reconstruction |
| `uv run python -m benchmarks.endurance --duration 600 --report endurance.json` | A long soak with incremental reports, allocation-growth limits and explicit failure outcomes |
| `uv run python -m benchmarks.review_evaluation` | Repeated live summaries with an OpenAI-compatible model (`PARSEFABRIC_LLM_API_KEY`, optional `PARSEFABRIC_LLM_BASE_URL` and `PARSEFABRIC_LLM_MODEL`) |

Every script accepts `--help`. `bench_parse` reports the controller process
only; work done inside process-pool workers is not included in its CPU and
memory figures.
