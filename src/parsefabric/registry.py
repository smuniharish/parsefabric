"""Parser registries: the `ParserRegistry` ABC, its in-memory default and plugin discovery."""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, override

from parsefabric.errors import DuplicateParserError, RegistryError
from parsefabric.parser import Parser

if TYPE_CHECKING:
    from collections.abc import Iterable

    from parsefabric.aggregation import Aggregate
    from parsefabric.capabilities import ParserCapabilities

__all__ = [
    "ENTRY_POINT_GROUP",
    "InMemoryParserRegistry",
    "ParserMetadata",
    "ParserRegistry",
]

ENTRY_POINT_GROUP = "parsefabric.parsers"
"""Entry-point group scanned by `ParserRegistry.discover`."""


@dataclass(frozen=True, slots=True)
class ParserMetadata:
    """Snapshot describing a registered parser.

    Attributes:
        name: Parser name.
        version: Parser version.
        parser_type: Class name of the parser.
        capabilities: Declared capabilities.
    """

    name: str
    version: str
    parser_type: str
    capabilities: ParserCapabilities


class ParserRegistry(ABC):
    """Name-to-parser registry whose lifetime its owner controls.

    There is no global registry: create one per application or component.
    Subclasses store parsers wherever the application needs, for example in
    a shared cache, by implementing `register_all`, `unregister`, `get` and
    `names`; `register`, `metadata` and `discover` build on those.
    `InMemoryParserRegistry` is the default.
    """

    @abstractmethod
    async def register_all(
        self, parsers: Iterable[Parser[Aggregate]], *, replace: bool = False
    ) -> None:
        """Register parsers atomically: either every parser or none.

        Args:
            parsers: Parsers to register under their names.
            replace: Replace parsers already registered under the same names.

        Raises:
            TypeError: If an item is not a `Parser`.
            DuplicateParserError: If two parsers share a name, or a name is
                taken and ``replace`` is false.
        """

    @abstractmethod
    async def unregister(self, name: str) -> Parser[Aggregate]:
        """Remove and return the parser registered under ``name``.

        Args:
            name: Parser name.

        Returns:
            The removed parser.

        Raises:
            RegistryError: If no parser has that name.
        """

    @abstractmethod
    async def get(self, name: str) -> Parser[Aggregate]:
        """Return the parser registered under ``name``.

        Args:
            name: Parser name.

        Returns:
            The registered parser.

        Raises:
            RegistryError: If no parser has that name.
        """

    @abstractmethod
    async def names(self) -> tuple[str, ...]:
        """Return the registered names in sorted order."""

    async def register(self, parser: Parser[Aggregate], *, replace: bool = False) -> None:
        """Register one parser under its name.

        Args:
            parser: Parser to register.
            replace: Replace a parser already registered under the same name.

        Raises:
            TypeError: If ``parser`` is not a `Parser`.
            DuplicateParserError: If the name is taken and ``replace`` is false.
        """
        await self.register_all((parser,), replace=replace)

    async def metadata(self, name: str) -> ParserMetadata:
        """Return a metadata snapshot for the parser registered under ``name``.

        Args:
            name: Parser name.

        Returns:
            The parser's name, version, type and capabilities.

        Raises:
            RegistryError: If no parser has that name.
        """
        parser = await self.get(name)
        return ParserMetadata(
            name=parser.name,
            version=parser.version,
            parser_type=type(parser).__name__,
            capabilities=parser.capabilities,
        )

    async def discover(self, group: str = ENTRY_POINT_GROUP) -> tuple[str, ...]:
        """Instantiate and register every installed parser entry point.

        Each entry point in ``group`` must reference a callable that takes no
        arguments and returns a parser. Loading an entry point imports and
        runs installed code, so only install trusted packages. Entry points
        load in a worker thread, so importing them does not block the event
        loop. Discovery is atomic: when any entry point fails, nothing is
        registered.

        Args:
            group: Entry-point group to scan.

        Returns:
            The names of the registered parsers, in discovery order.

        Raises:
            RegistryError: If an entry point cannot be loaded or does not
                produce a parser.
            DuplicateParserError: If a discovered name is already registered
                or used by two entry points.
        """
        discovered = await asyncio.to_thread(_load_entry_points, group)
        await self.register_all(discovered)
        return tuple(parser.name for parser in discovered)


def _load_entry_points(group: str) -> tuple[Parser[Aggregate], ...]:
    discovered: list[Parser[Aggregate]] = []
    for entry_point in entry_points(group=group):
        try:
            parser = entry_point.load()()
        except Exception as error:
            raise RegistryError(f"entry point {entry_point.name!r} could not be loaded") from error
        if not isinstance(parser, Parser):
            raise RegistryError(f"entry point {entry_point.name!r} did not load a Parser")
        discovered.append(parser)
    return tuple(discovered)


class InMemoryParserRegistry(ParserRegistry):
    """Thread-safe registry that keeps parsers in a process-local dictionary."""

    def __init__(self) -> None:
        self._parsers: dict[str, Parser[Aggregate]] = {}
        self._lock = threading.Lock()

    @override
    async def register_all(
        self, parsers: Iterable[Parser[Aggregate]], *, replace: bool = False
    ) -> None:
        selected = tuple(parsers)
        if any(not isinstance(parser, Parser) for parser in selected):
            raise TypeError("only Parser instances can be registered")
        names = [parser.name for parser in selected]
        repeated = {name for name in names if names.count(name) > 1}
        with self._lock:
            conflicts = sorted(
                repeated if replace else repeated | (set(names) & self._parsers.keys())
            )
            if conflicts:
                raise DuplicateParserError(f"parsers already registered or duplicated: {conflicts}")
            self._parsers.update((parser.name, parser) for parser in selected)

    @override
    async def unregister(self, name: str) -> Parser[Aggregate]:
        with self._lock:
            try:
                return self._parsers.pop(name)
            except KeyError as error:
                raise RegistryError(f"parser {name!r} is not registered") from error

    @override
    async def get(self, name: str) -> Parser[Aggregate]:
        with self._lock:
            try:
                return self._parsers[name]
            except KeyError as error:
                raise RegistryError(f"parser {name!r} is not registered") from error

    @override
    async def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._parsers))
