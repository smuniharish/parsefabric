"""Codecs: how aggregates are stored and how JSON documents are decoded.

Both are extension points. `ParseEngine` stores aggregates with an
`AggregateCodec` (by default `EvidenceCodec`, the versioned
``parsefabric.aggregates/1`` JSON format); `JSONParser` decodes documents with
a `JSONCodec` (by default `StrictJSONCodec`). Subclass either to use another
format, a faster decoder, compression or encryption.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, override

from parsefabric import _json
from parsefabric.aggregation.evidence import EvidenceAggregate
from parsefabric.errors import SerializationError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from parsefabric.aggregation import Aggregate

__all__ = [
    "AggregateCodec",
    "EvidenceCodec",
    "JSONCodec",
    "StrictJSONCodec",
]

_DOCUMENT_FIELDS = frozenset(("format", "aggregates"))


class AggregateCodec(ABC):
    """Encode aggregates for storage or transport, and decode them back.

    Implement `encode` and `decode` so that ``decode(encode(aggregates))``
    returns equal aggregates. Raise `SerializationError` for data that cannot
    be decoded. Pass an instance to ``ParseEngine(codec=...)``.
    """

    @property
    @abstractmethod
    def format(self) -> str:
        """Identifier of the wire format, such as ``"parsefabric.aggregates/1"``."""

    @abstractmethod
    async def encode(self, aggregates: Iterable[Aggregate], *, indent: int | None = None) -> str:
        """Encode aggregates as text.

        Args:
            aggregates: Aggregates to encode.
            indent: Indentation for human reading, if the format supports it.

        Returns:
            The encoded document.
        """

    @abstractmethod
    async def decode(self, data: str | bytes) -> tuple[Aggregate, ...]:
        """Decode and validate `encode` output.

        Args:
            data: Encoded text or bytes.

        Returns:
            The validated aggregates.

        Raises:
            SerializationError: If ``data`` is not a valid document.
        """


class EvidenceCodec(AggregateCodec):
    """The ``parsefabric.aggregates/1`` JSON format for `EvidenceAggregate`.

    Documents are ``{"format": "parsefabric.aggregates/1", "aggregates": [...]}``
    with exactly the documented fields; anything else is rejected.
    """

    FORMAT: ClassVar[str] = "parsefabric.aggregates/1"
    """Identifier written into every document."""

    @property
    @override
    def format(self) -> str:
        return self.FORMAT

    @override
    async def encode(self, aggregates: Iterable[Aggregate], *, indent: int | None = None) -> str:
        """Encode evidence aggregates, compact unless ``indent`` is given.

        Raises:
            TypeError: If an item is not an `EvidenceAggregate`.
        """
        items = []
        for aggregate in aggregates:
            if not isinstance(aggregate, EvidenceAggregate):
                raise TypeError(
                    f"EvidenceCodec encodes EvidenceAggregate, got {type(aggregate).__name__}"
                )
            items.append(aggregate._to_wire())
        document = {"format": self.FORMAT, "aggregates": items}
        return _json.dumps(document, indent=indent)

    @override
    async def decode(self, data: str | bytes) -> tuple[EvidenceAggregate, ...]:
        """Decode a ``parsefabric.aggregates/1`` document.

        Raises:
            TypeError: If ``data`` is not text or bytes.
            SerializationError: For malformed JSON, another format, unknown or
                missing fields, or an aggregate that fails validation.
        """
        try:
            document = _json.require_object(
                _json.loads(data), "aggregates document", _DOCUMENT_FIELDS
            )
            if document["format"] != self.FORMAT:
                raise ValueError(f"expected a {self.FORMAT} document")
            aggregates = document["aggregates"]
            if not isinstance(aggregates, list):
                raise ValueError("aggregates must be a list")
            return tuple(EvidenceAggregate.from_dict(item) for item in aggregates)
        except ValueError as error:
            raise SerializationError(f"invalid {self.FORMAT} document: {error}") from error


class JSONCodec(ABC):
    """Decode one JSON document for `JSONParser`.

    Implementations must return only JSON-compatible values (``dict`` with
    string keys, ``list``, ``str``, ``int``, finite ``float``, ``bool`` and
    ``None``) and raise `ValueError` for invalid documents. Offload heavy
    decoding with ``asyncio.to_thread`` if documents are large.
    """

    @abstractmethod
    async def decode(self, text: str) -> Any:
        """Decode one JSON document.

        Args:
            text: The document.

        Returns:
            The decoded value.

        Raises:
            ValueError: If the document is not valid JSON for this codec.
        """


class StrictJSONCodec(JSONCodec):
    """Standard-library decoder that accepts only strict RFC 8259 JSON.

    Duplicate object keys, ``NaN``/``Infinity``, numbers outside the float
    range such as ``1e400`` and nesting deeper than
    `parsefabric.MAX_JSON_DEPTH` are rejected. Integers of any size stay exact.
    """

    @override
    async def decode(self, text: str) -> Any:
        return _json.loads(text)
