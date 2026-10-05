# Testing

ParseFabric's test suite combines focused unit tests, property-based tests,
integration tests of the examples and documentation, and opt-in tests against
real services. Coverage of the package is held at 100% of lines and branches.

## Layout

| Directory | Contents |
| --- | --- |
| `tests/unit` | Focused tests of each module's behavior and failure paths |
| `tests/property` | Property-based tests with Hypothesis: models, parsers, aggregation, partitioning and stateful registry machines |
| `tests/integration` | The examples, the documentation snippets and diagrams, and the distributed-runtime adapters |
| `tests/benchmark` | Throughput gates and the summary-evaluation harness |
| `tests/live` | Tests against a real language model; skipped unless configured |
| `tests/support` | Shared strategies, parsers and helpers |

## Run the tests

```bash
uv run pytest                      # the whole suite
uv run pytest tests/unit           # one directory
uv run pytest -m "not slow"        # skip the slow example runs
uv run pytest -k aggregation       # tests whose names match
```

Warnings are errors, markers must be registered, and `xfail` is strict.

## Coverage

```bash
uv run coverage run -m pytest
uv run coverage report
```

The report fails below 100% line and branch coverage. The suite has no
coverage exclusions: code that no test can reach is removed instead.

## Property-based tests

Hypothesis profiles are selected with the `HYPOTHESIS_PROFILE` environment
variable:

| Profile | Examples per test | Behavior |
| --- | --- | --- |
| `ci` (default) | 300 | Derandomized, so every run explores the same cases |
| `dev` | 100 | Random, with the local example database for quick iteration |
| `thorough` | 2,000 | Random and deep; run before a release or after changing a parser |

```bash
HYPOTHESIS_PROFILE=thorough uv run pytest tests/property
```

## Documentation and examples

- `tests/integration/test_docs.py` runs every Python snippet in the
  documentation and the README, compares printed output with the documented
  output, and checks that every diagram PNG matches its Mermaid source.
- `tests/integration/test_examples.py` runs the offline examples against
  their recorded output in `examples/expected/`. The same check is available
  as a script:

  ```bash
  uv run python examples/verify_examples.py
  ```

## Live model tests

Tests in `tests/live` call a real OpenAI-compatible model. They are skipped
unless `PARSEFABRIC_LLM_API_KEY` is set; `PARSEFABRIC_LLM_BASE_URL` and
`PARSEFABRIC_LLM_MODEL` are optional. Copy `.env.example` to `.env` to keep
the values out of your shell history, never commit keys, and run:

```bash
uv run pytest -m live
```

Live results depend on the model, so the tests check the evidence contract
(cited facts, counts and line positions) rather than exact wording.

## Distributed runtimes

The Celery, Spark and Flink adapters have integration tests that run without
the runtimes. To run them on the real runtimes, use the Docker Compose profiles
described in [Distributed runtimes](../guide/distributed-runtimes.md).

## Benchmarks

The `benchmarks` package measures throughput, latency and memory on your
machine:

```bash
uv run python -m benchmarks.bench_parse --scale small
```

See the
[benchmarks README](https://github.com/smuniharish/parsefabric/blob/main/benchmarks/README.md)
for the soak, load and endurance scripts.
