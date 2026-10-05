"""Line partitioning for parsers that can parse independent chunks of a document."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from parsefabric.capabilities import ParserCapabilities
from parsefabric.observability import (
    LifecycleEvent,
    NullObservabilitySink,
    ObservabilitySink,
)
from parsefabric.parser._text import iter_text_lines

__all__ = [
    "LinePartitioner",
    "Partition",
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


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


class LinePartitioner:
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
        self._sink = sink or NullObservabilitySink()

    @property
    def max_lines(self) -> int:
        """Most records in one partition."""
        return self._max_lines

    @property
    def max_bytes(self) -> int:
        """Most UTF-8 bytes in one partition."""
        return self._max_bytes

    def partition(
        self,
        lines: Iterable[str],
        *,
        source_id: str | None = None,
        capabilities: ParserCapabilities,
    ) -> Iterator[Partition]:
        """Yield bounded partitions of complete records.

        Args:
            lines: Records, each optionally ending with one line terminator.
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
        for line_number, raw_line in enumerate(lines, start=1):
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
                len(buffer) >= self._max_lines
                or byte_count + record_bytes > self._max_bytes
            ):
                partition = Partition(
                    partition_id=str(partition_number),
                    source_id=source_id,
                    start_line=partition_start_line,
                    start_offset=offset - byte_count,
                    content="\n".join(buffer) + "\n",
                )
                self._emit_created(partition, len(buffer), byte_count)
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
            self._emit_created(partition, len(buffer), byte_count)
            yield partition

    def _emit_created(
        self,
        partition: Partition,
        line_count: int,
        byte_count: int,
    ) -> None:
        self._sink.emit(
            LifecycleEvent(
                "PartitionCreated",
                partition_id=partition.partition_id,
                attributes={"line_count": line_count, "byte_count": byte_count},
            )
        )
