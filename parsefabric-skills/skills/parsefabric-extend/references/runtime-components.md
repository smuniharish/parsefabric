# Runtime components

Read this when writing an execution backend, partitioner, observability
sink, language model, parser registry, tokenizer, code detector or command
output backend. The full guides are under
[Extending ParseFabric](https://parsefabric.readthedocs.io/en/latest/extending/).

## Execution backends

- Implement `async run(function, /, *args, **kwargs)` and
  `async shutdown()`. `map(function, items, *, max_in_flight)` has a
  default built on `run`; override it only for native batching.
- `run` awaits coroutine functions, returns the result, and propagates the
  callable's exception unchanged.
- `map` yields one result per item, raises the first failure, and cancels
  the rest.
- `shutdown` is idempotent and waits for running work. Backends are async
  context managers.
- Publish lifecycle events with `await self.emit(name, **attributes)`,
  which never raises.
- Cluster backends send callables and arguments to other processes: both
  must be picklable and importable by the workers. Ship results as JSON with
  `dumps_result` and `loads_result`.

## Partitioners

- `partition(lines, *, source_id, capabilities)` is an async iterator of
  `Partition(partition_id=, source_id=, start_line=, start_offset=, content=)`.
- Call `capabilities.require_partitionable()` first.
- Partitions are in source order, contiguous in lines and UTF-8 bytes, and
  start at line 1 and byte 0. Synchronous and asynchronous input must give
  the same partitions.

## Observability sinks

- `async emit(event)` must be fast and must not raise; buffer and send in
  `flush`. `close` flushes and releases connections.
- A `LifecycleEvent` has `name`, `parser_name`, `partition_id`, scalar
  `attributes` and `occurred_at`. It never contains parsed content.
- An exception from a sink is logged on `parsefabric.observability` and
  never fails the observed operation, but a raising sink still fails its
  contract check.

## Language models

- Implement `async complete(messages: Sequence[ChatMessage]) -> str`;
  override `name` for logs.
- The model owns authentication, retries and rate limits; the caller owns
  the time budget, such as `EvidenceSummarizer(timeout=...)`.
- Create the client once, inside the event loop that uses it; read keys
  from environment variables; close it at shutdown.
- Test with a scripted model; `check_language_model` calls it once.

## Parser registries

- Implement `async register_all(parsers, *, replace=False)`,
  `unregister(name)`, `get(name)` and `names()`. `register`, `metadata` and
  `discover` have defaults.
- `register_all` is atomic: a duplicate name raises `DuplicateParserError`
  and registers nothing. `get` of an unknown name raises `RegistryError`.
- `names` are sorted.

## Tokenizers

- `async count(text)` returns a non-negative integer, zero for empty text,
  never smaller when text is appended. `count_bytes` must agree for UTF-8.
- Offload slow tokenizers with `asyncio.to_thread`.

## Code detectors

- `async detect(text)` returns a language name or `None` for prose, the same
  answer every time.
- Download models or grammars in `prepare`, never in the constructor.

## Command output backends

- `name`, `validate(command)` (raise `ValueError` for unsupported commands)
  and `async parse(command, text)` returning JSON records.
- `CLIOutputParser(command=..., backend=...)` turns the records into events.
