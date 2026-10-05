# Distributed-runtime examples

These examples run unchanged ParseFabric parsers on Celery, Apache Spark and
Apache Flink, then check that the results and evidence returned by the
workers are identical to parsing locally. They are reference integrations,
not part of the `parsefabric` package.

All three use the same job contract: the driver sends a versioned JSON job
that names an allowlisted parser (`application-log` or the fixed
mixed-content parser in [`mixed_job.py`](mixed_job.py)), never a pickled
callable or caller-supplied configuration. Workers validate the job, parse,
and return a versioned `ParseResult` document.

| File | Purpose |
| --- | --- |
| [`celery_backend.py`](celery_backend.py) | Celery app, worker task and an `ExecutionBackend` that submits jobs |
| [`celery_example.py`](celery_example.py) | Checks remote results, failure propagation and cleanup |
| [`spark_batch.py`](spark_batch.py) | Bounded Spark batch adapter |
| [`spark_example.py`](spark_example.py) | Checks parity, rejection of unknown jobs and a throughput sample |
| [`flink_backend.py`](flink_backend.py) | Bounded PyFlink DataStream job and result reader |
| [`flink_job.py`](flink_job.py) | Submits the job and verifies its output |
| [`compose.yml`](compose.yml) | Services for all three runtimes |

Run the commands below from this directory with Docker (or Podman with
`podman compose`).

## Celery with Redis

```bash
docker compose --profile celery up --build --abort-on-container-exit --exit-code-from celery-example
docker compose --profile celery down
```

`PARSEFABRIC_CELERY_RECORDS` and `PARSEFABRIC_CELERY_SAMPLES` size the
throughput sample. Set `PARSEFABRIC_MIN_RECORDS_PER_SECOND` to fail the run
below a rate you choose for your machine.

## Apache Spark 4

```bash
docker compose --profile spark run --rm --build spark-example
```

Set `PARSEFABRIC_SPARK_MIN_RECORDS_PER_SECOND` to enforce a minimum sample
rate.

## Apache Flink 2

```bash
docker compose --profile flink up -d --build
docker compose exec flink-jobmanager flink run -py /workspace/examples/integrations/flink_job.py /results/output --records 32
docker compose exec flink-jobmanager python /workspace/examples/integrations/flink_job.py /results/output --verify --records 32
docker compose --profile flink down -v
```

The job waits for the task manager to register its slots. Use a new output
path for each run; Flink refuses to overwrite finished output.

## What the measurements mean

Each example prints a small, bounded throughput sample. It includes
submission and result collection on a single machine, so it is useful for
spotting regressions on that machine, not as a production capacity figure.
