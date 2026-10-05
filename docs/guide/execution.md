# Streaming and execution

ParseFabric separates **what** a parser does from **where** it runs. The
engine streams inputs through a parser with bounded concurrency; execution
backends run work on the event loop, in threads, in processes or on your own
infrastructure; and the partitioner splits large documents into pieces that
parse independently.

<figure class="diagram" markdown="span">
  ![Inputs are parsed one by one with parse_iter, concurrently with parse_async_iter, or split with LinePartitioner and mapped over an execution backend: asyncio, threads, processes or your own backend such as Celery; partition results are re-based and aggregated.](../assets/diagrams/execution.png){ width="769" }
  <figcaption>Choose how to run parsing based on the shape of your input.</figcaption>
</figure>

## Stream inputs

The engine accepts any iterable or async iterable of inputs:

| Method | Concurrency | Result order |
| --- | --- | --- |
| `parse_iter` | One input at a time | Input order |
| `parse_async_iter` | Up to `max_concurrency` inputs at once | Completion order |
| `parse_many` | One input at a time, for a finite batch | Input order, returned as a tuple |

All three accept `context` and `continue_on_error`. With
`continue_on_error=True`, a failing input yields a result with a
`ParseIssue` instead of ending the stream:

```python
--8<--
examples/streaming.py
--8<--
```

Output:

```text
--8<-- "examples/expected/streaming.txt"
```

Concurrency above 1 requires a parser whose capabilities declare
`parallel_safe`; otherwise `parse_async_iter` raises `CapabilityError`.
Inputs are consumed lazily, so at most `max_concurrency` inputs are in memory
at once. Closing or cancelling the iterator cancels the outstanding parses.

## Execution backends

Backends decide where work runs. They are asynchronous context managers that
release their resources on exit, and every backend offers the same two
operations:

- `await backend.run(function, *args, **kwargs)` runs one callable and
  returns its result, awaiting it when the callable is asynchronous.
- `backend.map(function, items, max_in_flight=n)` applies a callable to every
  item with at most `n` calls outstanding, yielding results in completion
  order. The first failure is raised and the remaining calls are cancelled.

| Backend | Runs work | Use it for |
| --- | --- | --- |
| `AsyncExecutionBackend` | On the event loop | Asynchronous, I/O-bound parsers |
| `ThreadExecutionBackend` | In a thread pool | Blocking I/O and libraries that release the GIL |
| `ProcessExecutionBackend` | In a spawn-based process pool | CPU-heavy parsing; callables, arguments and results must be picklable |

Parsers are independent of backends: the same parser runs on all of them and
produces identical results. To run work somewhere else, such as a task queue,
subclass `ExecutionBackend` and implement `run` and `shutdown`; `map` is
built on `run`.

```python
--8<--
examples/execution_backends.py
--8<--
```

Output:

```text
--8<-- "examples/expected/execution_backends.txt"
```

!!! warning "Cancellation stops waiting, not running work"

    Cancelling a thread or process call stops awaiting it, but Python cannot
    interrupt work that has already started; shutdown waits for it to finish.
    If a process worker dies, the pool raises `BrokenProcessPool` and refuses
    further work: shut the backend down and create a new one. Backends never
    retry work on their own. See [Failure handling](../operations/failure-handling.md).

## Partition large documents

A large line-oriented document can be split into bounded partitions that
parse independently, for example on several processes.
`LinePartitioner(max_lines=..., max_bytes=...)` yields `Partition` objects
that hold the partition's `content`, its first line number (`start_line`) and
its byte offset in the document (`start_offset`). It only accepts parsers
whose capabilities declare line framing, such as `ApplicationLogParser`.

Parse each partition with `ParseContext(source_offset=partition.start_offset)`
so byte spans stay document-relative, then re-base line numbers with
`start_line`:

```python
--8<--
examples/partitioning.py
--8<--
```

Output:

```text
--8<-- "examples/expected/partitioning.txt"
```

The partitioner normalizes every record's line terminator to a newline, so
partitioned parsing produces the same events as parsing the normalized
document whole. Records that contain a line boundary, or that exceed
`max_bytes` on their own, are rejected.

To run partitions on Celery, Apache Spark or Apache Flink, see
[Distributed runtimes](distributed-runtimes.md).
