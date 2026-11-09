# Streaming, execution backends and partitioning

Read this when parsing many inputs, large files, or work on several cores or
machines. The full guide is
[Streaming and execution](https://parsefabric.readthedocs.io/en/latest/guide/execution/).

## Stream inputs

| Method | Concurrency | Result order |
| --- | --- | --- |
| `engine.parse_iter(parser, sources)` | One input at a time | Input order |
| `engine.parse_async_iter(parser, sources, max_concurrency=n)` | Up to `n` at once | Completion order |
| `await engine.parse_many(parser, sources)` | One at a time, finite batch | Input order, as a tuple |

- `sources` is any iterable or async iterable; inputs are consumed lazily.
- All three accept `context` and `continue_on_error`. With
  `continue_on_error=True`, a failing input yields a result with a
  `ParseIssue` (carrying its `input_index`) instead of ending the stream.
- `max_concurrency` above 1 needs a `parallel_safe` parser, otherwise
  `CapabilityError`. Closing the iterator cancels outstanding parses.

## Execution backends

All are in `parsefabric.execution` and are async context managers:

| Backend | Runs work | Use it for |
| --- | --- | --- |
| `AsyncExecutionBackend` | On the event loop | Asynchronous, I/O-bound parsers |
| `ThreadExecutionBackend` | In a thread pool | Blocking I/O, libraries that release the GIL |
| `ProcessExecutionBackend` | In a spawn-based process pool | CPU-heavy parsing |
| `ExecutorBackend(executor)` | In any `concurrent.futures.Executor` | Custom or distributed pools |

<!-- docs-test: skip -->
```python
async with ProcessExecutionBackend(max_workers=4) as backend:
    async for item in backend.map(parse_partition, partitions, max_in_flight=8):
        ...
```

- `await backend.run(function, *args)` runs one callable; `backend.map`
  yields in completion order and cancels the rest on the first failure.
- Process work must be picklable, defined at module level, and started under
  `if __name__ == "__main__":`.
- Cancelling stops waiting, not running work. Pass `shutdown_timeout=` to
  bound shutdown. After `BrokenProcessPool`, create a new backend. Backends
  never retry.

## Partition large documents

`LinePartitioner(max_lines=..., max_bytes=...)` from
`parsefabric.partitioning` splits a line-oriented document for parsers whose
capabilities declare `"line"` framing, such as `ApplicationLogParser`.

<!-- docs-test: skip -->
```python
partitions = [
    partition
    async for partition in LinePartitioner(max_lines=500).partition(
        lines, source_id="app.log", capabilities=parser.capabilities
    )
]
```

1. Parse each partition with
   `ParseContext(source_id=partition.source_id, source_offset=partition.start_offset)`
   so byte spans stay document-relative.
2. Re-base line numbers:
   `partition.start_line + event.evidence.line_number - 1`, applied with
   `event.with_evidence(replace(event.evidence, line_number=...))`.
3. Sort the results by `start_line`, then aggregate all the events of the
   document **together**; never merge per-partition aggregates of one
   document.

The partitioner normalizes line terminators to `\n`, so compare against the
joined `partition.content` values, not the raw file, when you verify.
`examples/partitioning.py` in the repository is a complete, verified
pipeline.

## Distributed runtimes

Celery, Apache Spark and Apache Flink adapters are shown in
[Distributed runtimes](https://parsefabric.readthedocs.io/en/latest/integrations/distributed-runtimes/).
The driver sends versioned JSON jobs naming an allowlisted parser, workers
return results as versioned JSON from `dumps_result`, and the driver decodes
them with `loads_result`, then aggregates and verifies the events in one
place. Never let a job name an arbitrary import path.
