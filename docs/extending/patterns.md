# Patterns

A pattern recognizes one kind of value and turns a match into an event. The
built-in patterns cover regular expressions, exact values, predicates and
mappings; see [Patterns](../guide/custom-parsers.md#patterns). Write your own
when matching needs logic that does not fit them, such as a tokenizer for a
`key=value` format.

Subclass `Pattern` and implement `match(value)`, which returns a
`PatternMatch` with the event's attributes, and optionally its severity and
confidence, or `None` when the value does not match. The base class stores
the name, priority, metadata and event type, and `to_event` turns a match
into an event; parsers add the evidence.

`match` is synchronous on purpose: it runs once per line and pattern, so it
must be fast and must not do I/O. It must also be deterministic and
thread-safe, because `DeterministicParser` promises both. Keep attributes
JSON-compatible.

```python
import asyncio

from parsefabric import ParseEngine
from parsefabric.parser import DeterministicParser
from parsefabric.patterns import Pattern, PatternMatch
from parsefabric.testing import check_pattern


class HTTPStatusPattern(Pattern):
    """Match `key=value` access-log lines whose status is 400 or above."""

    def match(self, value: object) -> PatternMatch | None:
        if not isinstance(value, str):
            return None
        fields = dict(item.split("=", 1) for item in value.split() if "=" in item)
        status = fields.get("status", "")
        if not status.isdigit() or int(status) < 400:
            return None
        severity = "ERROR" if int(status) >= 500 else "WARNING"
        return PatternMatch({"status": int(status), "path": fields.get("path")}, severity)


async def main() -> None:
    pattern = HTTPStatusPattern("http_error")
    check_pattern(pattern, "status=503 path=/pay", "status=200 path=/pay")

    parser = DeterministicParser([pattern], name="access")
    lines = "status=200 path=/\nstatus=404 path=/old\nstatus=503 path=/pay\n"
    result = await ParseEngine().parse(parser, lines)
    for event in result.events:
        print(event.evidence.line_number, event.severity, event.attributes)


asyncio.run(main())
```

```text
2 WARNING {'status': 404, 'path': '/old'}
3 ERROR {'status': 503, 'path': '/pay'}
```

Pass your pattern anywhere a built-in pattern goes: to `DeterministicParser`,
to `ApplicationLogParser(patterns=)`, to `CLIOutputParser(patterns=)` and as
a route selector of `MixedContentParser`.

`check_pattern(pattern, matching, other)` checks that the pattern describes
itself, matches `matching` the same way every time, produces events of its
event type and does not match `other`.
