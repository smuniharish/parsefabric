# Parser registries

A `ParserRegistry` maps names to parser instances. There is no global
registry: create one per application or component. Every method is a
coroutine. `InMemoryParserRegistry` keeps parsers in a thread-safe
dictionary:

```python
import asyncio

from parsefabric.builtins import ApplicationLogParser, JSONParser
from parsefabric.registry import InMemoryParserRegistry


async def main() -> None:
    registry = InMemoryParserRegistry()
    await registry.register_all((ApplicationLogParser(), JSONParser()))
    metadata = await registry.metadata("json")
    print(await registry.names(), metadata.parser_type)


asyncio.run(main())
```

```text
('application-log', 'json') JSONParser
```

`register_all` is atomic: either every parser is registered or none is, and
a name that is taken raises `DuplicateParserError` unless you pass
`replace=True`. `get` and `unregister` raise `RegistryError` for unknown
names.

## Subclass ParserRegistry

To keep parsers somewhere else, subclass `ParserRegistry` and implement
`register_all`, `unregister`, `get` and `names`; `register`, `metadata` and
`discover` work unchanged on top of them. This registry layers overrides for
one tenant over a shared registry:

```python
import asyncio
from collections.abc import Iterable

from parsefabric import DuplicateParserError, Parser, RegistryError
from parsefabric.builtins import ApplicationLogParser, JSONParser, TimestampedLogParser
from parsefabric.registry import InMemoryParserRegistry, ParserRegistry
from parsefabric.testing import check_parser_registry


class LayeredRegistry(ParserRegistry):
    """Look parsers up in local overrides first, then in a shared registry."""

    def __init__(self, shared: ParserRegistry) -> None:
        self._shared = shared
        self._local: dict[str, Parser] = {}
        self._lock = asyncio.Lock()

    async def register_all(self, parsers: Iterable[Parser], *, replace: bool = False) -> None:
        selected = {parser.name: parser for parser in parsers}
        async with self._lock:
            taken = sorted(set(selected) & set(self._local))
            if taken and not replace:
                raise DuplicateParserError(f"parsers already registered: {taken}")
            self._local.update(selected)

    async def unregister(self, name: str) -> Parser:
        async with self._lock:
            if name not in self._local:
                raise RegistryError(f"parser {name!r} is not a local override")
            return self._local.pop(name)

    async def get(self, name: str) -> Parser:
        async with self._lock:
            local = self._local.get(name)
        return local if local is not None else await self._shared.get(name)

    async def names(self) -> tuple[str, ...]:
        async with self._lock:
            local = set(self._local)
        return tuple(sorted(local | set(await self._shared.names())))


async def main() -> None:
    await check_parser_registry(
        LayeredRegistry(InMemoryParserRegistry()), [ApplicationLogParser(), JSONParser()]
    )

    shared = InMemoryParserRegistry()
    await shared.register_all((ApplicationLogParser(), JSONParser()))
    tenant = LayeredRegistry(shared)
    await tenant.register(TimestampedLogParser())
    print(await tenant.names())
    print(type(await tenant.get("json")).__name__)


asyncio.run(main())
```

```text
('application-log', 'json', 'timestamped-log')
JSONParser
```

## Publish parser plugins

Packages can publish parsers as plugins through the `parsefabric.parsers`
entry-point group. Each entry point must reference a callable that takes no
arguments and returns a parser, such as a parser class:

```toml
[project.entry-points."parsefabric.parsers"]
access-log = "acme_parsers.access:AccessLogParser"
```

`await registry.discover()` loads every installed entry point in a worker
thread and registers the parsers it returns; pass a group name to scan another
entry-point group. Discovery is atomic: if any entry point fails, nothing is
registered. Loading an entry point imports and runs installed code, so only
install packages you trust.
