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
| Very large or continuous volumes | Your own backend on a cluster; see [Distributed runtimes](../integrations/distributed-runtimes.md) |

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
  most expensive step for unclaimed lines. Pass a
  `TreeSitterCodeDetector` with only the languages you expect, or
  `code_detector=None` to turn detection off. Detection results for short
  texts are cached, so share one detector between parsers.
- **Store aggregates, not events.** Aggregates of deterministic parsers store
  line positions instead of events, so repetitive logs shrink substantially:
  the bursty incident log in the [aggregation example](../examples.md#aggregation)
  is stored in 91% fewer bytes. `measure_compression` reports the savings for
  your data.

## Memory

| Operation | Holds in memory |
| --- | --- |
| `parse` | One input and its result |
| `parse_many` | Every input's result, returned together |
| `parse_async_iter` | At most `max_concurrency` inputs and their results; results are yielded as they finish |
| `ExecutionBackend.map` | At most `max_in_flight` calls |
| `aggregate` with `EvidenceAggregator` | One entry per distinct message and its positions; retained events only for parsers that cannot be re-parsed |
| `aggregate` with `RoutingAggregator` | The events of one document, grouped by route, until each route's aggregator runs |
| `EventAccumulator` | One count and time range per group |
| `materialize` | The re-parsed events of one document |

Use `parse_async_iter` instead of `parse_many` for unbounded streams, and
`EventAccumulator` when you only need counts across many documents.

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
