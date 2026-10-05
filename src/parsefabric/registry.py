"""Instance-owned parser registry with explicit entry-point discovery."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from threading import RLock

from parsefabric.capabilities import ParserCapabilities
from parsefabric.errors import DuplicateParserError, RegistryError
from parsefabric.parser import Parser

__all__ = [
    "ENTRY_POINT_GROUP",
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


class ParserRegistry:
    """Thread-safe name-to-parser registry whose lifetime its owner controls.

    There is no global registry: create one per application or component.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}
        self._lock = RLock()

    def register(self, parser: Parser, *, replace: bool = False) -> None:
        """Register a parser under its name.

        Args:
            parser: Parser to register.
            replace: Replace a parser already registered under the same name.

        Raises:
            TypeError: If ``parser`` is not a `Parser`.
            DuplicateParserError: If the name is taken and ``replace`` is false.
        """
        if not isinstance(parser, Parser):
            raise TypeError("only Parser instances can be registered")
        with self._lock:
            if parser.name in self._parsers and not replace:
                raise DuplicateParserError(
                    f"parser {parser.name!r} is already registered"
                )
            self._parsers[parser.name] = parser

    def unregister(self, name: str) -> Parser:
        """Remove and return the parser registered under ``name``.

        Args:
            name: Parser name.

        Returns:
            The removed parser.

        Raises:
            RegistryError: If no parser has that name.
        """
        with self._lock:
            try:
                return self._parsers.pop(name)
            except KeyError as error:
                raise RegistryError(f"parser {name!r} is not registered") from error

    def get(self, name: str) -> Parser:
        """Return the parser registered under ``name``.

        Args:
            name: Parser name.

        Returns:
            The registered parser.

        Raises:
            RegistryError: If no parser has that name.
        """
        with self._lock:
            try:
                return self._parsers[name]
            except KeyError as error:
                raise RegistryError(f"parser {name!r} is not registered") from error

    def metadata(self, name: str) -> ParserMetadata:
        """Return a metadata snapshot for the parser registered under ``name``.

        Args:
            name: Parser name.

        Returns:
            The parser's name, version, type and capabilities.

        Raises:
            RegistryError: If no parser has that name.
        """
        parser = self.get(name)
        return ParserMetadata(
            name=parser.name,
            version=parser.version,
            parser_type=type(parser).__name__,
            capabilities=parser.capabilities,
        )

    def names(self) -> tuple[str, ...]:
        """Return the registered names in sorted order."""
        with self._lock:
            return tuple(sorted(self._parsers))

    def discover(self) -> tuple[str, ...]:
        """Instantiate and register every installed parser entry point.

        Each entry point in the `ENTRY_POINT_GROUP` group must reference
        a callable that takes no arguments and returns a parser. Loading an
        entry point imports and runs installed code, so only install trusted
        packages. Discovery is atomic: when any entry point fails, nothing is
        registered.

        Returns:
            The names of the registered parsers, in discovery order.

        Raises:
            RegistryError: If an entry point cannot be loaded or does not
                produce a parser.
            DuplicateParserError: If a discovered name is already registered
                or used by two entry points.
        """
        discovered: list[Parser] = []
        for entry_point in entry_points(group=ENTRY_POINT_GROUP):
            try:
                parser = entry_point.load()()
            except Exception as error:
                raise RegistryError(
                    f"entry point {entry_point.name!r} could not be loaded"
                ) from error
            if not isinstance(parser, Parser):
                raise RegistryError(
                    f"entry point {entry_point.name!r} did not load a Parser"
                )
            discovered.append(parser)
        names = [parser.name for parser in discovered]
        with self._lock:
            conflicts = sorted(
                {name for name in names if names.count(name) > 1}
                | (set(names) & self._parsers.keys())
            )
            if conflicts:
                raise DuplicateParserError(
                    f"parsers already registered or duplicated: {conflicts}"
                )
            for parser in discovered:
                self._parsers[parser.name] = parser
        return tuple(names)
