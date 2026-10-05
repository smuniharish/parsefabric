"""Package-owned, versioned JSON encoding of parser output.

Every parser produces the same `EvidenceAggregate` documents, so there
is exactly one closed wire format and nothing to extend. The public entry
points are the package-managed `Parser.serialize` and
`Parser.deserialize`; this module is their implementation.
"""

from __future__ import annotations

from collections.abc import Iterable

from parsefabric import _json
from parsefabric.aggregation.evidence import EvidenceAggregate
from parsefabric.errors import SerializationError

FORMAT = "parsefabric.aggregates/1"
"""Identifier of the aggregate wire format written by `encode`."""

_DOCUMENT_FIELDS = frozenset(("format", "aggregates"))


def encode(
    aggregates: Iterable[EvidenceAggregate], *, indent: int | None = None
) -> str:
    """Encode evidence as JSON text, compact unless ``indent`` is given.

    Args:
        aggregates: Aggregates to encode.
        indent: Indentation for human reading.

    Returns:
        A ``parsefabric.aggregates/1`` document.

    Raises:
        TypeError: If an item is not an `EvidenceAggregate`.
    """
    items = []
    for aggregate in aggregates:
        if not isinstance(aggregate, EvidenceAggregate):
            raise TypeError(
                "only EvidenceAggregate can be serialized, "
                f"got {type(aggregate).__name__}"
            )
        items.append(aggregate._to_wire())
    document = {"format": FORMAT, "aggregates": items}
    if indent is None:
        return _json.dumps_validated(document)
    return _json.dumps(document, indent=indent)


def decode(text: str | bytes) -> tuple[EvidenceAggregate, ...]:
    """Decode and validate `encode` output.

    Args:
        text: JSON text or UTF-8 bytes.

    Returns:
        The validated aggregates.

    Raises:
        TypeError: If ``text`` is not text or bytes.
        SerializationError: For malformed JSON, an unsupported format, unknown
            or missing fields, or any aggregate that fails validation.
    """
    try:
        document = _json.require_object(
            _json.loads(text), "aggregates document", _DOCUMENT_FIELDS
        )
        if document["format"] != FORMAT:
            raise ValueError(f"expected a {FORMAT} document")
        aggregates = document["aggregates"]
        if not isinstance(aggregates, list):
            raise ValueError("aggregates must be a list")
        return tuple(EvidenceAggregate.from_dict(item) for item in aggregates)
    except ValueError as error:
        raise SerializationError(f"invalid {FORMAT} document: {error}") from error
