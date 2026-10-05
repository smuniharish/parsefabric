"""Typed exceptions and the serializable parse issue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from parsefabric._json import JSONValue, check_text, require_object

__all__ = [
    "CapabilityError",
    "ConfigurationError",
    "DuplicateParserError",
    "IntegrityError",
    "ParseError",
    "ParseFabricError",
    "ParseIssue",
    "RegistryError",
    "SerializationError",
    "SummaryValidationError",
]


class ParseFabricError(Exception):
    """Base class for every exception raised by ParseFabric."""


class ParseError(ParseFabricError):
    """A parser cannot interpret its input."""


class ConfigurationError(ParseFabricError, ValueError):
    """A parser or runtime configuration is invalid."""


class RegistryError(ParseFabricError):
    """A parser registry operation is invalid."""


class DuplicateParserError(RegistryError):
    """A parser with the same name is already registered."""


class CapabilityError(ParseFabricError):
    """The requested operation conflicts with a parser's declared capabilities."""


class SerializationError(ParseFabricError, ValueError):
    """A value cannot be encoded to, or decoded from, a supported JSON format."""


class IntegrityError(ParseFabricError, ValueError):
    """Aggregates cannot be materialized into verified original events."""


class SummaryValidationError(ParseFabricError, ValueError):
    """An LLM summary did not pass bounded evidence review."""


_ISSUE_FIELDS = frozenset(("error_type", "message", "source_id", "input_index"))


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """A serializable failure recorded in a tolerant parse result.

    Attributes:
        error_type: Name of the exception class.
        message: Exception message.
        source_id: Source document that failed, if known.
        input_index: Zero-based position of the failed input in a batch, if
            known.
    """

    error_type: str
    message: str
    source_id: str | None = None
    input_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.error_type, str) or not self.error_type:
            raise ValueError("issue error_type must be a non-empty string")
        check_text(self.error_type, "issue error_type")
        if not isinstance(self.message, str):
            raise ValueError("issue message must be a string")
        check_text(self.message, "issue message")
        if self.source_id is not None:
            if not isinstance(self.source_id, str):
                raise ValueError("issue source_id must be a string or None")
            check_text(self.source_id, "issue source_id")
        if self.input_index is not None and (
            type(self.input_index) is not int or self.input_index < 0
        ):
            raise ValueError("issue input_index must be a non-negative integer")

    @classmethod
    def from_exception(
        cls,
        error: BaseException,
        *,
        source_id: str | None = None,
        input_index: int | None = None,
    ) -> Self:
        """Summarize an exception by its type name and message.

        Args:
            error: The exception raised by a parser.
            source_id: Source document that failed.
            input_index: Position of the failed input in a batch.

        Returns:
            The issue. Characters that are not valid Unicode are escaped.
        """
        message = (
            str(error)
            .encode("utf-8", errors="backslashreplace")
            .decode("utf-8", errors="strict")
        )
        return cls(
            error_type=type(error).__name__,
            message=message,
            source_id=source_id,
            input_index=input_index,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Return the JSON-compatible representation."""
        return {
            "error_type": self.error_type,
            "message": self.message,
            "source_id": self.source_id,
            "input_index": self.input_index,
        }

    @classmethod
    def from_dict(cls, data: object) -> Self:
        """Rebuild an issue from `to_dict` output.

        Args:
            data: A decoded JSON object.

        Returns:
            The validated issue.

        Raises:
            ValueError: If ``data`` does not have exactly the issue fields or
                a field is invalid.
        """
        fields = require_object(data, "parse issue", _ISSUE_FIELDS)
        return cls(**fields)
