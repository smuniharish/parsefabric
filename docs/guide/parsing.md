# Parsing and evidence

Every parser turns one input into a `ParseResult`: a sequence of events, each
with evidence of where it came from, plus any recorded issues and match
statistics. This page explains those building blocks and how the engine
completes them.

<figure class="diagram" markdown="span">
  ![A source and its ParseContext go to parser.parse, which produces events with line, byte span and pattern evidence; the engine fills missing source, parser, version, partition and correlation fields; failures with continue_on_error become ParseIssue records; everything ends up in a ParseResult.](../assets/diagrams/parse-flow.png){ width="525" }
  <figcaption>The parser records positions and patterns; the engine fills
  identifying fields that the parser left empty.</figcaption>
</figure>

## Run a parser

`ParseEngine.parse(parser, source, context)` awaits `parser.parse` and then:

- fills evidence fields that the parser left empty (`source_id`,
  `parser_name`, `parser_version`, `partition_id`, `correlation_id`) from the
  context and the parser's identity,
- records a failure as a `ParseIssue` instead of raising it when you pass
  `continue_on_error=True`, and
- reports lifecycle events to an
  [observability sink](observability.md).

You can also call `await parser.parse(source, context)` directly. The
built-in parsers fill their own evidence, so the events are the same; you only
lose the lifecycle events and the error tolerance.

## Describe the input

`ParseContext` describes where an input comes from. Every field is optional:

| Field | Meaning |
| --- | --- |
| `source_id` | Name of the source, such as a file name or stream identifier |
| `correlation_id` | Identifier that ties the parse to a request, job or trace |
| `partition_id` | Identifier of the partition when a document is split |
| `source_offset` | Byte offset of this input within its document; shifts every byte span |

## Events

A `ParsedEvent` is one normalized finding:

| Field | Meaning |
| --- | --- |
| `event_type` | Kind of finding, such as `timeout` or `json_record` |
| `attributes` | JSON-compatible details, such as `message` or `level` |
| `timestamp` | Timezone-aware time of the finding, if known |
| `severity` | Severity label, such as `ERROR`, if known |
| `confidence` | Number between 0 and 1, for parsers that estimate it |
| `evidence` | Where the event came from |

Events are immutable and validated when they are created. Attributes must be
JSON-compatible (strings, finite numbers, booleans, `None`, lists and
string-keyed objects, nested at most `MAX_JSON_DEPTH` levels) and are copied,
so a mapping you keep using cannot change an event. Naive timestamps,
confidence outside 0–1 and empty event types raise `ValueError`.

## Evidence

`Evidence` records the provenance of one event:

| Field | Filled by |
| --- | --- |
| `line_number` | The parser: 1-based line of the match |
| `start_offset`, `end_offset` | The parser: UTF-8 byte span, line terminator included |
| `pattern_name` | The parser: the pattern that matched |
| `source_id` | The parser or the engine, from the context |
| `parser_name`, `parser_version` | The parser or the engine, from the parser's identity |
| `partition_id`, `correlation_id` | The parser or the engine, from the context |

Byte offsets refer to the UTF-8 encoding of the input, so you can slice the
original bytes with `data[start_offset:end_offset]` even when the text
contains non-ASCII characters. Line-oriented parsers split lines on the same
boundaries as `str.splitlines`.

## Results

| Field | Meaning |
| --- | --- |
| `events` | Parsed events in source order |
| `warnings` | Non-fatal messages from the parser |
| `errors` | `ParseIssue` records of failures that were recorded instead of raised |
| `pattern_statistics` | Match count of every pattern, including patterns that never matched |
| `parser_name`, `parser_version` | The parser that produced the result |
| `correlation_id` | The correlation identifier of the parse |
| `llm_result` | An optional [evidence summary](summaries.md) attached to the result |

## Failures

Parser exceptions propagate by default; cancellation always propagates. With
`continue_on_error=True`, the engine returns a result whose `errors` holds a
`ParseIssue` with the exception type and message, so one bad input does not
stop a stream. Some parsers record expected problems as issues on their own:
`JSONParser` and `CLIOutputParser`, for example, return an `unparsed` event
and an issue for input they cannot decode.

All ParseFabric exceptions derive from `ParseFabricError`; see the
[errors reference](../reference/errors.md).

## Serialize results

`dumps_result` and `loads_result` convert results to and from strict JSON, and
`iter_ndjson` writes one result per line for log pipelines:

```python
import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser
from parsefabric.serialization import dumps_result, iter_ndjson, loads_result


async def main() -> None:
    engine = ParseEngine()
    parser = ApplicationLogParser()
    results = [
        await engine.parse(parser, line, ParseContext(source_id="api.log"))
        for line in ("upstream timed out", "permission denied for user 7")
    ]

    restored = loads_result(dumps_result(results[0]))
    print("round trip:", restored == results[0])
    lines = list(iter_ndjson(results))
    event_types = [loads_result(line).events[0].event_type for line in lines]
    print(len(lines), "NDJSON lines:", event_types)


asyncio.run(main())
```

Output:

```text
round trip: True
2 NDJSON lines: ['timeout', 'authorization_failure']
```

Decoding is strict: unknown or missing fields, duplicate keys, non-finite
numbers and invalid UTF-8 raise `SerializationError`. Every result and event
carries a `schema_version` that identifies its format.
