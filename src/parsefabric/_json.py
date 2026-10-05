"""Strict JSON helpers shared by ParseFabric's models and wire formats."""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any, cast

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]

MAX_JSON_DEPTH = 256
"""Deepest nesting of lists and objects accepted in a JSON value."""

STRUCTURE_DEPTH = MAX_JSON_DEPTH + 16
"""Nesting allowed for package documents that embed JSON values."""

_INVALID = (
    "must be JSON-compatible: strings, finite numbers, booleans, null, "
    "lists, and objects with string keys"
)
_ENCODER = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
_SORTED_ENCODER = json.JSONEncoder(
    ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
)
# Validated model values are trees, so these encoders skip cycle checks.
_CANONICAL_ENCODER = json.JSONEncoder(
    ensure_ascii=False,
    allow_nan=False,
    separators=(",", ":"),
    sort_keys=True,
    check_circular=False,
)
_VALIDATED_ENCODER = json.JSONEncoder(
    ensure_ascii=False, allow_nan=False, separators=(",", ":"), check_circular=False
)


def check_text(value: str, what: str) -> str:
    """Return ``value`` if it is valid Unicode text (no lone surrogates).

    Args:
        value: Text to check.
        what: Description used in the error message.

    Returns:
        The unchanged text.

    Raises:
        ValueError: If the text cannot be encoded as UTF-8.
    """
    if not value.isascii():
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{what} must be valid Unicode text") from error
    return value


def _is_scalar(value: object, what: str) -> bool:
    """Validate a JSON scalar; return ``False`` for lists and objects."""
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, str):
        check_text(value, what)
        return True
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{what} must not contain non-finite numbers")
        return True
    if isinstance(value, (list, dict)):
        return False
    raise ValueError(f"{what} {_INVALID}")


def copy_json(
    value: object, what: str = "JSON value", *, max_depth: int = MAX_JSON_DEPTH
) -> Any:
    """Validate a JSON-compatible value and return an independent deep copy.

    Lists and objects are copied so that callers cannot mutate a validated
    value through a reference they still hold. Nesting is limited to
    ``max_depth`` levels, which also rejects self-referencing containers.

    Args:
        value: Candidate JSON value.
        what: Description used in error messages.
        max_depth: Deepest accepted nesting of lists and objects.

    Returns:
        A deep copy containing only JSON-compatible values.

    Raises:
        ValueError: If the value is not JSON-compatible.
    """
    if type(value) is dict:
        flat = _copy_flat_object(value, what)
        if flat is not None:
            return flat
    elif _is_scalar(value, what):
        return value
    root: list[Any] | dict[str, Any] = [] if isinstance(value, list) else {}
    stack: list[tuple[object, list[Any] | dict[str, Any], int]] = [(value, root, 1)]
    while stack:
        source, target, depth = stack.pop()
        if depth > max_depth:
            raise ValueError(f"{what} nests deeper than {max_depth} levels")
        # Every target was created with the same container type as its source.
        if isinstance(target, list):
            for item in cast("list[Any]", source):
                target.append(_copy_child(item, what, stack, depth))
        else:
            for key, item in cast("dict[Any, Any]", source).items():
                if not isinstance(key, str):
                    raise ValueError(f"{what} object keys must be strings")
                check_text(key, what)
                target[key] = _copy_child(item, what, stack, depth)
    return root


def _copy_child(
    item: object,
    what: str,
    stack: list[tuple[object, list[Any] | dict[str, Any], int]],
    depth: int,
) -> Any:
    """Return a scalar, or an empty container scheduled to receive its copy."""
    if _is_scalar(item, what):
        return item
    child: list[Any] | dict[str, Any] = [] if isinstance(item, list) else {}
    stack.append((item, child, depth + 1))
    return child


def _copy_flat_object(value: dict[Any, Any], what: str) -> dict[str, Any] | None:
    """Copy an object of exact scalar types; ``None`` defers to the general path."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        if type(key) is not str:
            return None
        if not key.isascii():
            check_text(key, what)
        if type(item) is str:
            if not item.isascii():
                check_text(item, what)
        elif not (item is None or type(item) is int or type(item) is bool):
            return None
        result[key] = item
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        counts = Counter(key for key, _ in pairs)
        duplicates = sorted(key for key, count in counts.items() if count > 1)
        raise ValueError(f"duplicate JSON object key {duplicates[0]!r}")
    return result


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not a JSON number")


def loads(payload: str | bytes | bytearray) -> Any:
    """Decode one strict RFC 8259 JSON document.

    Bytes must be UTF-8. Duplicate object keys, ``NaN``/``Infinity`` and
    nesting too deep for the decoder are rejected.

    Args:
        payload: JSON text or UTF-8 bytes.

    Returns:
        The decoded value.

    Raises:
        TypeError: If ``payload`` is not text or bytes.
        ValueError: If the payload is not strict JSON.
    """
    if isinstance(payload, (bytes, bytearray)):
        text = bytes(payload).decode("utf-8")
    elif isinstance(payload, str):
        text = payload
    else:
        raise TypeError("JSON payload must be str or bytes")
    try:
        return json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except RecursionError as error:
        raise ValueError("JSON document nests too deeply") from error


def dumps(value: object, *, indent: int | None = None, sort_keys: bool = False) -> str:
    """Encode a JSON-compatible value as compact UTF-8-safe JSON text."""
    if indent is None:
        return (_SORTED_ENCODER if sort_keys else _ENCODER).encode(value)
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, indent=indent, sort_keys=sort_keys
    )


def canonical_dumps(value: object) -> str:
    """Encode a validated value as canonical JSON: compact with sorted keys."""
    return _CANONICAL_ENCODER.encode(value)


def dumps_validated(value: object) -> str:
    """Encode an already-validated, acyclic value as compact JSON."""
    return _VALIDATED_ENCODER.encode(value)


def require_object(
    value: object,
    what: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Return ``value`` if it is a JSON object with exactly the allowed keys.

    Args:
        value: Decoded JSON value.
        what: Description used in error messages.
        required: Keys that must be present.
        optional: Keys that may be present.

    Returns:
        The object.

    Raises:
        ValueError: If ``value`` is not an object, lacks a required key, or
            contains an unknown key.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object")
    keys = value.keys()
    if keys == required:
        return value
    missing = required - keys
    if missing:
        raise ValueError(f"{what} is missing {', '.join(sorted(missing))}")
    unknown = keys - required - optional
    if unknown:
        raise ValueError(f"{what} has unknown fields {', '.join(sorted(unknown))}")
    return value
