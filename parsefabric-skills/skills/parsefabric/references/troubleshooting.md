# Troubleshooting

Read this when parsing, storage or summaries fail. The full list is
[Failure handling](https://parsefabric.readthedocs.io/en/latest/operations/failure-handling/).

| Symptom | Cause | Fix |
| --- | --- | --- |
| `IntegrityError` from `materialize` | The source, the context or the parser version differs from the one the aggregates were made with | Store the source unchanged, with its context and parser version, and materialize with the same parser |
| `SerializationError` from `deserialize` | The stored document was edited, truncated, or written by another codec | Decode with the codec that encoded it; never edit stored aggregates |
| `ValueError` from `aggregate` | Events from several sources, out of order, or from two parser versions | Aggregate one source at a time, in source order |
| `CapabilityError` from `merge_aggregates` | Both aggregates cover the same source document | Merge partitions of one source, not two copies of it |
| `CapabilityError` from the partitioner | The parser is not line-partitionable | Parse the whole source, or use a line-partitionable parser |
| Line numbers restart in each partition | Events were not re-based | Pass `source_offset=partition.start_offset` in the context and add `partition.start_line - 1` to each line number; see [execution.md](execution.md) |
| `RuntimeWarning: coroutine ... was never awaited` | An async method was called without `await` | Await it; in synchronous code, wrap the entry point in `asyncio.run` |
| An expected event is missing | The input did not match the parser's patterns | Check `result.errors` and `unparsed` events, or choose another parser |
| A code language is not detected | Tree-sitter grammars are downloaded on first use, which fails offline | Run `await TreeSitterCodeDetector().prepare()` while building the image, or pass `code_detector=None` |
| `BrokenProcessPool` | A process worker died | Shut down the backend, create a new one, and decide whether repeating the work is safe |
| `SummaryValidationError` | The model could not produce a supported summary within `max_revisions` | Use a stronger model, smaller `max_aggregates`, or a higher `max_revisions`; never return the rejected draft |

ParseFabric never retries a parse: retry policy belongs to the application,
since parsers can have side effects and streams may not be replayable.
