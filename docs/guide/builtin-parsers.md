# Built-in parsers

ParseFabric includes parsers for the most common kinds of operational text.
They all live in `parsefabric.builtins`, are deterministic, and fill their own
evidence.

| Parser | Input | Events | Partitionable |
| --- | --- | --- | --- |
| [`ApplicationLogParser`](#application-logs) | Free-form application logs | One per matching pattern per line | Yes, by line |
| [`TimestampedLogParser`](#timestamped-logs) | `TIMESTAMP LEVEL message` lines | `log`, one per line | No |
| [`JSONParser`](#json) | One JSON document or decoded value | `json_record` or `unparsed` | No |
| [`PythonTracebackParser`](#python-tracebacks) | One Python traceback | `python_exception` | No |
| [`CLIOutputParser`](#command-output) | Command output | `cli_record` per record, or pattern events | No |
| [`MixedContentParser`](mixed-content.md) | Documents that mix logs, JSON, code and text | Routed, pattern, `code`, `fence` and `other` events | No |

The example below runs four of them:

```python
--8<--
examples/builtin_parsers.py
--8<--
```

Output:

```text
--8<-- "examples/expected/builtin_parsers.txt"
```

## Application logs

`ApplicationLogParser` recognizes common failure signals anywhere in a line.
Every line is checked against every pattern, so one line can produce several
events. Signal patterns record the line, without trailing whitespace, as
`message`; `error` and `warning` record the text after the level.

| Pattern | Matches (case-insensitive) | Severity | Priority |
| --- | --- | --- | --- |
| `service_down` | service down, service stopped, unavailable | `ERROR` | 20 |
| `connection_failure` | connection refused, connection reset, connect failed | `ERROR` | 20 |
| `authentication_failure` | authentication failed, invalid credentials, login failed | `ERROR` | 20 |
| `authorization_failure` | authorization failed, permission denied, forbidden | `ERROR` | 20 |
| `timeout` | timeout, timed out | `ERROR` | 15 |
| `oom` | OOM, out of memory | `CRITICAL` | 15 |
| `retry` | retry, retrying, attempt *N* | none | 10 |
| `stack_trace` | `Traceback (most recent call last):` (case-sensitive) | `ERROR` | 10 |
| `error` | the word `ERROR` | `ERROR` | 5 |
| `warning` | `WARN` or `WARNING` | `WARNING` | 5 |

Patterns run in descending priority, ties broken by name. To replace the
defaults, pass your own patterns; `ApplicationLogParser([])` has no patterns at
all. To extend them, start from `default_patterns()`:

```python
import asyncio
import re

from parsefabric import ParseEngine
from parsefabric.builtins import ApplicationLogParser
from parsefabric.builtins.application_log import default_patterns
from parsefabric.patterns import RegexPattern

parser = ApplicationLogParser(
    [
        *default_patterns(),
        RegexPattern(
            "disk_full",
            r"no space left on device (?P<device>\S+)",
            flags=re.IGNORECASE,
            priority=20,
            severity="CRITICAL",
        ),
    ]
)


async def main() -> None:
    result = await ParseEngine().parse(
        parser, "write failed: No space left on device /dev/sdb1\n"
    )
    for event in result.events:
        print(event.event_type, event.severity, event.attributes)


asyncio.run(main())
```

Output:

```text
disk_full CRITICAL {'device': '/dev/sdb1'}
```

## Timestamped logs

`TimestampedLogParser` parses documents in which **every** line is a
`TIMESTAMP LEVEL message` record with a timezone-aware ISO 8601 timestamp.
Each line becomes a `log` event with `level` and `message` attributes, the
parsed timestamp, and the level as severity. A line that does not match, or a
timestamp without a time zone, raises `ParseError` naming the line.

Pass `line_pattern` for another layout. It must define the named groups `at`,
`level` and `message` and match a whole line:

```python
import asyncio

from parsefabric import ParseEngine
from parsefabric.builtins import TimestampedLogParser

parser = TimestampedLogParser(
    line_pattern=r"^\[(?P<at>[^\]]+)\] (?P<level>[A-Z]+): (?P<message>.+)$"
)


async def main() -> None:
    result = await ParseEngine().parse(
        parser, "[2026-10-01T08:00:03+00:00] ERROR: disk failing\n"
    )
    (event,) = result.events
    print(event.timestamp.isoformat(), event.severity, event.attributes["message"])


asyncio.run(main())
```

Output:

```text
2026-10-01T08:00:03+00:00 ERROR disk failing
```

## JSON

`JSONParser` parses one JSON document from text or bytes, or accepts an
already-decoded value, and produces one `json_record` event whose `value`
attribute holds the document. Invalid JSON is not raised: the result holds an
`unparsed` event with the text and a `ParseIssue`. Documents nested deeper
than `MAX_JSON_DEPTH` (256) levels are invalid. To parse JSON lines inside a
larger document, route them from a
[`MixedContentParser`](mixed-content.md).

## Python tracebacks

`PythonTracebackParser` turns one traceback into a single `python_exception`
event with `exception_type`, `message` and `frames` attributes; each frame has
`file`, `line` and `function`. The exception is the last line that looks like
`ExceptionType: message`, and the evidence spans the whole input.

## Command output

`CLIOutputParser` works in one of two modes:

- **jc mode.** `CLIOutputParser(command="df")` parses the whole output with
  the [jc](https://github.com/kellyjonbrazil/jc) parser of that name. Each
  record becomes a `cli_record` event whose attributes are the record. Output
  that jc rejects becomes an `unparsed` event plus a `ParseIssue`, and
  non-blank output in which jc finds no records produces a warning. Run
  `python -c "import jc; print(jc.parser_mod_list())"` to list the available
  commands; streaming parsers (names ending in `_s`) are not supported.
- **Pattern mode.** `CLIOutputParser([pattern, ...])` matches every line
  against your patterns, like a [`DeterministicParser`](custom-parsers.md).

## Detect code

`CodeDetector` reports which tree-sitter grammar, if any, parses a block of
text as code. `MixedContentParser` uses it for lines that no route or pattern
claims, and you can use it on its own:

```python
from parsefabric.builtins import CodeDetector

detector = CodeDetector()
print(detector.detect("def charge(order):\n    return gateway.charge(order)"))
print(detector.detect("SELECT id FROM orders WHERE total > 10"))
print(detector.detect("the payment failed again"))
```

Output:

```text
python
sql
None
```

The default languages are `DEFAULT_CODE_LANGUAGES`: Python, JavaScript,
TypeScript, Java, Go, Rust, C, C++ and SQL, tried in that order. Grammars that
accept ordinary prose, such as Bash or Ruby, are rejected because they would
classify plain sentences as code. Missing grammars are downloaded when the
detector is created; see
[Installation](../getting-started/installation.md#code-detection-grammars).
