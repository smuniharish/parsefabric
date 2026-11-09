# Partitioners

A partitioner splits a large document into `Partition` objects that parse
independently, so that partitions can run on several processes or machines.
`LinePartitioner` cuts line-oriented documents into chunks of at most
`max_lines` records and `max_bytes` bytes. Write your own to cut at other
boundaries, such as blank lines between multi-line records or the record
boundaries of a storage format.

Subclass `Partitioner` and implement
`partition(lines, *, source_id=None, capabilities)` as an async generator
that yields `Partition` objects. A partition holds its `content`, its
`partition_id`, the document's `source_id`, its first line number
(`start_line`) and its byte offset in the document (`start_offset`).

Every partitioner follows the same rules:

- **Check the parser first.** Call `capabilities.require_framing("line")`, or
  the framing your partitions need, so that parsers that read whole documents
  raise `CapabilityError` instead of producing wrong results.
- **Yield partitions in source order** with unique `partition_id` values and
  the given `source_id`.
- **Keep partitions contiguous.** Each partition starts at the line
  (`start_line`, 1-based) and UTF-8 byte (`start_offset`) where the previous
  one ended, so results re-base onto the whole document.
- **Accept both iterables and async iterables** of records, such as a file
  read line by line.
- **Publish lifecycle events** with `parsefabric.observability.publish`.

A partitioner that keeps blank-line-separated paragraphs together:

```python
import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable

from parsefabric import ParserCapabilities
from parsefabric.builtins import ApplicationLogParser
from parsefabric.partitioning import Partition, Partitioner
from parsefabric.testing import check_partitioner


async def records(lines: Iterable[str] | AsyncIterable[str]) -> AsyncIterator[str]:
    if isinstance(lines, AsyncIterable):
        async for line in lines:
            yield line
    else:
        for line in lines:
            yield line


class ParagraphPartitioner(Partitioner):
    """End a partition at every blank line."""

    async def partition(
        self,
        lines: Iterable[str] | AsyncIterable[str],
        *,
        source_id: str | None = None,
        capabilities: ParserCapabilities,
    ) -> AsyncIterator[Partition]:
        capabilities.require_framing("line")
        buffer: list[str] = []
        start_line, offset, number = 1, 0, 0
        async for line in records(lines):
            buffer.append(line.rstrip("\r\n"))
            if buffer[-1]:
                continue
            content = "\n".join(buffer) + "\n"
            yield Partition(str(number), source_id, start_line, offset, content)
            start_line += len(buffer)
            offset += len(content.encode("utf-8"))
            number += 1
            buffer = []
        if buffer:
            content = "\n".join(buffer) + "\n"
            yield Partition(str(number), source_id, start_line, offset, content)


async def main() -> None:
    lines = ["db timeout", "db retry", "", "cache miss", "", "disk full"]
    capabilities = ApplicationLogParser().capabilities
    partitions = await check_partitioner(ParagraphPartitioner(), lines, capabilities=capabilities)
    for partition in partitions:
        print(partition.partition_id, partition.start_line, partition.start_offset)


asyncio.run(main())
```

```text
0 1 0
1 4 21
2 6 33
```

`check_partitioner(partitioner, lines, capabilities=...)` checks the order,
identifiers, source identifier and contiguity of the partitions, and that a
list and an async stream of the same records partition identically.

Parse each partition with `ParseContext(source_offset=partition.start_offset)`
so byte spans stay document-relative, and add `start_line - 1` to event line
numbers; [Streaming and execution](../guide/execution.md#partition-large-documents)
shows the full flow on a process pool.
