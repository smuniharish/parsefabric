"""Partitioning: split one document into chunks that parse independently."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from parsefabric.observability import (
    LifecycleEvent,
    NullObservabilitySink,
    ObservabilitySink,
    publish,
)
from parsefabric.parser._text import iter_text_lines

if TYPE_CHECKING:
    from parsefabric.capabilities import ParserCapabilities

__all__ = [
    "LinePartitioner",
    "Partition",
    "Partitioner",
]


@dataclass(frozen=True, slots=True)
class Partition:
    """A bounded chunk of line records with its location in the source.

    Attributes:
        partition_id: Zero-based partition number, as text.
        source_id: Source document identifier.
        start_line: One-based source line of the first record.
        start_offset: UTF-8 byte offset of the first record in the
            normalized document.
        content: The records joined with newlines; every partition except
            the last ends with a newline.
    """

    partition_id: str
    source_id: str | None
    start_line: int
    start_offset: int
    content: str


async def _records(lines: Iterable[str] | AsyncIterable[str]) -> AsyncIterator[str]:
    if isinstance(lines, AsyncIterable):
        async for line in lines:
            yield line
    else:
        for line in lines:
            yield line


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


class Partitioner(ABC):
    """Split a document into `Partition` objects that parse independently.

    Implement `partition` as an asynchronous generator. Check the parser's
    `ParserCapabilities` first (for example with
    `ParserCapabilities.require_framing`) and yield partitions in source
    order with `Partition.start_line` and `Partition.start_offset` set so that
    results can be re-based onto the whole document. Publish lifecycle events
    with `parsefabric.observability.publish`.
    """

    @abstractmethod
    def partition(
        self,
        lines: Iterable[str] | AsyncIterable[str],
        *,
        source_id: str | None = None,
        capabilities: ParserCapabilities,
    ) -> AsyncIterator[Partition]:
        """Yield partitions of a document in source order.

        Args:
            lines: The document's records, from a synchronous or
                asynchronous iterable.
            source_id: Source document identifier copied into partitions.
            capabilities: Capabilities of the parser that will parse the
                partitions.

        Yields:
            Partitions in source order.
        """


class LinePartitioner(Partitioner):
    """Split complete text records into bounded, independently parsable chunks.

    Every record's own line terminator is normalized to a newline, so a
    document parsed partition by partition produces the same events as the
    normalized document parsed whole (after re-basing line numbers with
    `Partition.start_line` and offsets with
    `Partition.start_offset`).

    Args:
        max_lines: Most records in one partition.
        max_bytes: Most UTF-8 bytes in one partition, newlines included.
        sink: Destination for ``PartitionCreated`` lifecycle events.

    Raises:
        ValueError: If a limit is not a positive integer.
    """

    def __init__(
        self,
        *,
        max_lines: int = 1000,
        max_bytes: int = 1_048_576,
        sink: ObservabilitySink | None = None,
    ) -> None:
        self._max_lines = _positive(max_lines, "max_lines")
        self._max_bytes = _positive(max_bytes, "max_bytes")
        if sink is not None and not isinstance(sink, ObservabilitySink):
            raise TypeError("sink must be an ObservabilitySink")
        self._sink = sink if sink is not None else NullObservabilitySink()

    @property
    def max_lines(self) -> int:
        """Most records in one partition."""
        return self._max_lines

    @property
    def max_bytes(self) -> int:
        """Most UTF-8 bytes in one partition."""
        return self._max_bytes

    @override
    async def partition(
        self,
        lines: Iterable[str] | AsyncIterable[str],
        *,
        source_id: str | None = None,
        capabilities: ParserCapabilities,
    ) -> AsyncIterator[Partition]:
        """Yield bounded partitions of complete records.

        Args:
            lines: Records, each optionally ending with one line terminator,
                from a synchronous or asynchronous iterable such as a file
                read line by line.
            source_id: Source document identifier copied into partitions.
            capabilities: Capabilities of the parser that will parse the
                partitions; they must allow line-framed partitioning.

        Yields:
            Partitions in source order.

        Raises:
            CapabilityError: If the parser cannot parse line partitions.
            TypeError: If a record is not a string.
            ValueError: If a record contains a line boundary or exceeds
                ``max_bytes`` on its own.
        """
        capabilities.require_framing("line")
        buffer: list[str] = []
        byte_count = 0
        offset = 0
        partition_start_line = 1
        partition_number = 0
        line_number = 0
        async for raw_line in _records(lines):
            line_number += 1
            if not isinstance(raw_line, str):
                raise TypeError("line partitioner requires strings")
            framed = iter_text_lines(raw_line)
            record, width = next(framed, ("", 0))
            if next(framed, None) is not None:
                raise ValueError(f"line {line_number} must contain exactly one record")
            delimiter = raw_line[len(record) :]
            record_bytes = width - len(delimiter.encode("utf-8")) + 1
            if record_bytes > self._max_bytes:
                raise ValueError(f"line {line_number} exceeds the partition byte limit")
            if buffer and (
                len(buffer) >= self._max_lines or byte_count + record_bytes > self._max_bytes
            ):
                partition = Partition(
                    partition_id=str(partition_number),
                    source_id=source_id,
                    start_line=partition_start_line,
                    start_offset=offset - byte_count,
                    content="\n".join(buffer) + "\n",
                )
                await self._emit_created(partition, len(buffer), byte_count)
                yield partition
                buffer = []
                byte_count = 0
                partition_start_line = line_number
                partition_number += 1
            buffer.append(record)
            byte_count += record_bytes
            offset += record_bytes
        if buffer:
            partition = Partition(
                partition_id=str(partition_number),
                source_id=source_id,
                start_line=partition_start_line,
                start_offset=offset - byte_count,
                content="\n".join(buffer),
            )
            await self._emit_created(partition, len(buffer), byte_count)
            yield partition

    async def _emit_created(
        self,
        partition: Partition,
        line_count: int,
        byte_count: int,
    ) -> None:
        if type(self._sink) is not NullObservabilitySink:
            await publish(
                self._sink,
                LifecycleEvent(
                    "PartitionCreated",
                    partition_id=partition.partition_id,
                    attributes={"line_count": line_count, "byte_count": byte_count},
                ),
            )
