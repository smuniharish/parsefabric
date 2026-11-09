# Distributed runtimes

ParseFabric parsers do not depend on where they run. The repository includes
reference integrations that run unchanged parsers on **Celery**, **Apache
Spark** and **Apache Flink**, and check that the results and evidence
returned by the workers are identical to parsing locally. They are examples to
adapt, not part of the installed package.

## The job contract

All three integrations exchange the same kind of messages, so no executable
code crosses the wire:

- The driver sends a **versioned JSON job** that names an allowlisted parser
  and carries the input text and its `ParseContext`. Jobs never contain
  pickled callables or caller-supplied parser configuration.
- The worker validates the job, rejecting unknown versions, unknown parsers,
  unexpected fields, duplicate keys, non-finite numbers and oversized
  inputs, then parses the input.
- The worker returns the `ParseResult` as a versioned JSON document produced
  by `dumps_result`, which the driver decodes and validates with
  `loads_result`.

Because results carry their evidence, the driver can aggregate, store and
materialize them exactly as if they had been parsed locally.

## Celery

[`celery_backend.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/integrations/celery_backend.py)
implements an `ExecutionBackend` that submits jobs to a Celery worker through
Redis, so `backend.run` and `backend.map` work exactly as with the built-in
backends. Worker failures propagate to the caller; timeouts surface as errors,
and revoking a job that is already running is best-effort.

## Apache Spark

[`spark_batch.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/integrations/spark_batch.py)
validates a bounded batch of jobs on the driver, parses them in Spark tasks
with `mapPartitions`, and returns the results in input order after checking
that none are missing or duplicated.

## Apache Flink

[`flink_backend.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/integrations/flink_backend.py)
runs a bounded PyFlink DataStream job that parses each record and writes the
result documents to a file sink, which the driver reads back and verifies.

## Run the examples

The integrations ship with a Docker Compose file that uses one profile per
runtime. From `examples/integrations` in a checkout:

=== "Celery"

    ```bash
    docker compose --profile celery up --build --abort-on-container-exit --exit-code-from celery-example
    docker compose --profile celery down
    ```

=== "Spark"

    ```bash
    docker compose --profile spark run --rm --build spark-example
    ```

=== "Flink"

    ```bash
    docker compose --profile flink up -d --build
    docker compose exec flink-jobmanager flink run -py /workspace/examples/integrations/flink_job.py /results/output --records 32
    docker compose exec flink-jobmanager python /workspace/examples/integrations/flink_job.py /results/output --verify --records 32
    docker compose --profile flink down -v
    ```

Podman users can run the same commands with `podman compose`. Each example
prints a small throughput sample that includes submission and result
collection on one machine; use it to spot regressions, not as a capacity
figure. See the
[integrations README](https://github.com/smuniharish/parsefabric/tree/main/examples/integrations)
for the tuning variables.

!!! warning "Secure the transport"

    The job contract validates what workers accept, but it does not
    authenticate callers or encrypt traffic. Run brokers and clusters behind
    your own authentication, authorization and network controls. See
    [Security](../operations/security.md).
