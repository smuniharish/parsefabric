# Performance

ParseFabric is designed to process large volumes of text predictably:
built-in patterns run in linear time, streams are consumed lazily with bounded
concurrency, and aggregates of deterministic parsers store line positions
instead of events. Actual throughput depends on your input, your patterns, the
backend and the machine, so measure the workload you care about.

## Choose an execution strategy

| Workload | Approach |
| --- | --- |
| Many small inputs, such as lines from a queue | `ParseEngine.parse_async_iter` with `max_concurrency` |
| I/O-bound parsers, such as `AsyncParser` subclasses | The event loop: `parse_async_iter` or `AsyncExecutionBackend` |
| Blocking libraries that release the GIL | `ThreadExecutionBackend` |
| Large documents and CPU-heavy parsing | `LinePartitioner` with `ProcessExecutionBackend` |
| Very large or continuous volumes | Your own backend on a cluster; see [Distributed runtimes](../guide/distributed-runtimes.md) |

## Tune

- **Bound work in flight.** `max_concurrency` and `max_in_flight` limit memory
  as well as parallelism. Start near the number of cores for CPU-bound work
  and raise it for I/O-bound work.
- **Size partitions.** Larger partitions amortize scheduling and pickling
  overhead; smaller ones bound memory per worker and balance load. The
  `LinePartitioner` defaults, 1,000 lines and 1 MiB per partition, are a
  reasonable starting point.
- **Emit fewer events.** `first_match_only=True` stops at the first matching
  pattern on each line. Give frequent patterns higher priority.
- **Limit code detection.** In `MixedContentParser`, code detection is the
  most expensive step for unclaimed lines. Pass only the `code_languages` you
  expect, or `()` to turn detection off. Detection results for short texts are
  cached.
- **Store aggregates, not events.** Aggregates of deterministic parsers store
  line positions instead of events, so repetitive logs shrink substantially:
  the bursty incident log in the [aggregation example](../examples.md#aggregation)
  is stored in 82% fewer bytes. `measure_compression` reports the savings for
  your data.

## Measure

The repository includes benchmarks that report wall time, CPU time and memory
for parsing, streaming, partitioning, aggregation, serialization and each
execution backend. From a checkout:

```bash
uv run python -m benchmarks.bench_parse --scale small
```

When you evaluate throughput, measure with your own parsers and a realistic
input distribution at several scales, include serialization and result
collection in the measured span, and look at tail latency as well as
averages. Process-pool workers run outside the measuring process, so measure
their CPU and memory separately. Treat results as specific to the machine and
workload that produced them.
