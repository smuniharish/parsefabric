"""Versioned JSON and NDJSON encoding of parse results."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from parsefabric import _json
from parsefabric.errors import SerializationError
from parsefabric.models import ParseResult

__all__ = [
    "dumps_result",
    "iter_ndjson",
    "loads_result",
]


def dumps_result(result: ParseResult) -> str:
    """Encode a parse result as compact, strict JSON.

    Args:
        result: The result to encode.

    Returns:
        JSON text; non-ASCII characters are written as UTF-8, not escaped.

    Raises:
        TypeError: If ``result`` is not a `ParseResult`.
    """
    if not isinstance(result, ParseResult):
        raise TypeError("dumps_result expects a ParseResult")
    return _json.dumps_validated(result._to_wire())


def loads_result(payload: str | bytes) -> ParseResult:
    """Decode and validate a parse result written by `dumps_result`.

    The document must contain exactly the version-1 result fields. Duplicate
    object keys, non-finite numbers and invalid UTF-8 are rejected.

    Args:
        payload: JSON text or UTF-8 bytes.

    Returns:
        The validated result.

    Raises:
        TypeError: If ``payload`` is not text or bytes.
        SerializationError: If the document is not a valid parse result.
    """
    try:
        return ParseResult.from_dict(_json.loads(payload))
    except ValueError as error:
        raise SerializationError(f"invalid parse result JSON: {error}") from error


def iter_ndjson(results: Iterable[ParseResult]) -> Iterator[str]:
    """Encode results as newline-delimited JSON, one line per result.

    Args:
        results: Results to encode.

    Yields:
        One JSON document followed by a newline per result.
    """
    for result in results:
        yield dumps_result(result) + "\n"
