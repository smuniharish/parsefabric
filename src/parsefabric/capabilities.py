"""Parser capabilities that orchestration code checks before scheduling work."""

from __future__ import annotations

from dataclasses import dataclass, fields

from parsefabric.errors import CapabilityError

__all__ = [
    "ParserCapabilities",
]


@dataclass(frozen=True, slots=True)
class ParserCapabilities:
    """Behavioral guarantees a parser makes to the code that runs it.

    Attributes:
        deterministic: The same input and context always produce the same
            result.
        incremental: The parser handles inputs one at a time from a stream.
        stateful: Results depend on earlier inputs.
        requires_order: Inputs must be parsed in order.
        parallel_safe: One instance may parse several inputs concurrently.
        partitionable: A document may be split and its chunks parsed
            independently; requires a deterministic, parallel-safe, stateless,
            order-independent parser and a ``partition_framing``.
        partition_framing: Record framing of partitions, such as ``"line"``.
        aggregatable: Events may be aggregated by the package.

    Raises:
        ValueError: If a flag is not a bool or the combination is unsafe.
    """

    deterministic: bool = False
    incremental: bool = False
    stateful: bool = False
    requires_order: bool = False
    parallel_safe: bool = False
    partitionable: bool = False
    partition_framing: str | None = None
    aggregatable: bool = False

    def __post_init__(self) -> None:
        for item in fields(self):
            if item.name != "partition_framing" and not isinstance(
                getattr(self, item.name), bool
            ):
                raise ValueError(f"capability {item.name} must be a bool")
        if self.partition_framing is not None and (
            not isinstance(self.partition_framing, str) or not self.partition_framing
        ):
            raise ValueError("partition_framing must be a non-empty string or None")
        if self.partitionable and not (
            self.deterministic
            and self.parallel_safe
            and not self.stateful
            and not self.requires_order
        ):
            raise ValueError(
                "partitionable parsers must be deterministic, parallel-safe, "
                "stateless, and order-independent"
            )
        if self.partitionable != (self.partition_framing is not None):
            raise ValueError(
                "partitionable parsers must declare a partition framing, "
                "and only partitionable parsers may declare one"
            )
        if self.stateful and self.parallel_safe:
            raise ValueError("stateful parsers cannot declare parallel_safe")
        if self.requires_order and self.parallel_safe:
            raise ValueError("order-dependent parsers cannot declare parallel_safe")

    def require_partitionable(self) -> None:
        """Raise unless independent partitions may be parsed.

        Raises:
            CapabilityError: If the parser is not partitionable.
        """
        if not self.partitionable:
            raise CapabilityError(
                "parser capabilities do not allow independent partition execution"
            )

    def require_framing(self, framing: str) -> None:
        """Raise unless partitions with the given record framing may be parsed.

        Args:
            framing: Required framing, such as ``"line"``.

        Raises:
            CapabilityError: If the parser is not partitionable or uses a
                different framing.
        """
        self.require_partitionable()
        if self.partition_framing != framing:
            raise CapabilityError(
                f"parser partition framing {self.partition_framing!r} "
                f"does not match {framing!r}"
            )

    def require_parallel_safe(self) -> None:
        """Raise unless one instance may parse concurrently.

        Raises:
            CapabilityError: If the parser is not parallel-safe.
        """
        if not self.parallel_safe:
            raise CapabilityError("parser capabilities do not allow parallel execution")
