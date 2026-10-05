"""Asynchronous parser abstraction."""

from __future__ import annotations

from abc import abstractmethod
from typing import override

from parsefabric.capabilities import ParserCapabilities
from parsefabric.models import ParseContext, ParseResult
from parsefabric.parser.base import Parser, validated_identity


class AsyncParser(Parser):
    """Base class for parsers that await I/O, such as a service call, while parsing.

    Subclasses implement `parse`. Capabilities default to aggregatable
    only: output is not assumed to be deterministic or safe to parse
    concurrently, so aggregation retains every event.

    Args:
        name: Non-empty parser name.
        version: Non-empty parser version.

    Raises:
        ValueError: If ``name`` or ``version`` is empty or not a string.
    """

    def __init__(self, *, name: str, version: str = "1") -> None:
        self._name, self._version = validated_identity(name, version)

    @property
    @override
    def name(self) -> str:
        return self._name

    @property
    @override
    def version(self) -> str:
        return self._version

    @property
    @override
    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(aggregatable=True)

    @abstractmethod
    @override
    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        """Parse one input into a structured result."""
