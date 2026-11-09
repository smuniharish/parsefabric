# Codecs

Codecs decide how ParseFabric reads and writes JSON-shaped data. There are
two extension points:

| ABC | Default | Pass it to | Decides |
| --- | --- | --- | --- |
| `AggregateCodec` | `EvidenceCodec`, the `parsefabric.aggregates/1` format | `ParseEngine(codec=)` | How `engine.serialize` and `engine.deserialize` store aggregates |
| `JSONCodec` | `StrictJSONCodec`, strict RFC 8259 JSON | `JSONParser(codec=)` | How JSON input documents are decoded |

## Store aggregates

Subclass `AggregateCodec` and implement:

| Member | Contract |
| --- | --- |
| `format` | Identifier of the wire format, written into documents so readers can reject others |
| `async encode(aggregates, *, indent=None)` | Return the document as text, deterministically |
| `async decode(data)` | Accept text or UTF-8 bytes, return equal aggregates, and raise `SerializationError` for anything invalid |

A codec for the per-severity counts of the [aggregator example](aggregators.md),
which `EvidenceCodec` does not store:

```python
import asyncio
import json
from collections.abc import Iterable

from parsefabric import ParseEngine, SerializationError
from parsefabric.aggregation import Aggregate, CountAggregate
from parsefabric.codecs import AggregateCodec
from parsefabric.testing import check_codec


class CountCodec(AggregateCodec):
    """Store CountAggregate values as a versioned JSON document."""

    @property
    def format(self) -> str:
        return "acme.counts/1"

    async def encode(self, aggregates: Iterable[Aggregate], *, indent: int | None = None) -> str:
        items = []
        for aggregate in aggregates:
            if not isinstance(aggregate, CountAggregate):
                raise TypeError("CountCodec stores CountAggregate values")
            items.append(aggregate.to_dict())
        return json.dumps({"format": self.format, "counts": items}, indent=indent)

    async def decode(self, data: str | bytes) -> tuple[CountAggregate, ...]:
        try:
            document = json.loads(data)
            if document.get("format") != self.format:
                raise ValueError(f"expected a {self.format} document")
            return tuple(CountAggregate.from_dict(item) for item in document["counts"])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise SerializationError(f"invalid {self.format} document: {error}") from error


async def main() -> None:
    counts = (CountAggregate("severity", 2, None, None, {"severity": "ERROR"}),)
    engine = ParseEngine(codec=CountCodec())
    stored = await engine.serialize(counts)
    print(stored)
    print(await engine.deserialize(stored) == counts)
    await check_codec(CountCodec(), counts)


asyncio.run(main())
```

```text
{"format": "acme.counts/1", "counts": [{"event_type": "severity", "count": 2, "key_attributes": {"severity": "ERROR"}}]}
True
```

`check_codec(codec, aggregates)` checks that encoding is deterministic and
that decoding the text, or its UTF-8 bytes, returns equal aggregates.
Compress or encrypt stored documents around the codec, in the code that
writes them to storage.

## JSON documents

`JSONParser` decodes its input with a `JSONCodec`. Subclass it and implement
`async decode(text)`, which returns JSON-compatible values (`dict` with
string keys, `list`, `str`, `int`, finite `float`, `bool` or `None`) and
raises `ValueError` for invalid documents. The parser turns a `ValueError`
into a `ParseIssue`. Offload heavy decoding with `asyncio.to_thread`.

This codec accepts whole-line `//` comments, as in many configuration files,
and leaves the strict checks to `StrictJSONCodec`:

```python
import asyncio
from typing import Any

from parsefabric import ParseEngine
from parsefabric.builtins import JSONParser
from parsefabric.codecs import StrictJSONCodec
from parsefabric.testing import check_json_codec


class CommentedJSONCodec(StrictJSONCodec):
    """Strict JSON that may contain whole-line // comments."""

    async def decode(self, text: str) -> Any:
        lines = [line for line in text.splitlines() if not line.lstrip().startswith("//")]
        return await super().decode("\n".join(lines))


async def main() -> None:
    await check_json_codec(CommentedJSONCodec())
    config = '{\n  // seconds before a retry\n  "retry_after": 30\n}'
    result = await ParseEngine().parse(JSONParser(codec=CommentedJSONCodec()), config)
    print([event.attributes for event in result.events])


asyncio.run(main())
```

```text
[{'value': {'retry_after': 30}}]
```

`check_json_codec(codec)` checks that standard documents decode to the
standard values, with large integers kept exact, and that malformed
documents raise `ValueError`.
