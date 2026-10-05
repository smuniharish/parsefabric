# Mixed content

Incident notes, chat transcripts, runbooks, CI logs and language-model output
rarely contain one format. `MixedContentParser` parses such documents line by
line: it routes each line to the parser that understands it, parses fenced
blocks by language, detects unfenced code, and keeps everything else as text.
**No line is lost**: every line produces at least one event.

## How lines are classified

<figure class="diagram" markdown="span">
  ![For each line: a code fence sends its body to the parser for the fence language, falling back to code events; otherwise a matching route whose parser returns events wins; otherwise a matching line pattern produces an event; otherwise the block becomes a code event when it parses as code, or an other event with the text.](../assets/diagrams/mixed-content.png){ width="784" }
  <figcaption>Each line is classified by the first rule that applies.</figcaption>
</figure>

1. **Code fences.** A Markdown fence (```` ``` ```` or `~~~`) starts a fenced
   block. The body goes to the parser registered in `fence_routes` for the
   fence's language tag. Without such a parser, or when it rejects the body,
   every body line becomes a `code` event; body lines that the parser skips
   stay `code` too. The fence marker lines become `fence` events.
2. **Routes.** The first route whose selector pattern matches sends the line
   to an existing parser. Its events keep their own parser identity, with
   evidence re-based to the line. A route to a `JSONParser` continues over the
   following lines until the JSON value is complete. If the routed parser
   returns no events, the next route is tried.
3. **Patterns.** The first matching pattern, in priority order, produces an
   event. By default, a single `log-level` pattern recognizes
   `LEVEL message` lines, optionally after an ISO date, and records `level`,
   `message`, `text` and the severity.
4. **Code detection and text.** Remaining lines are grouped into indentation
   blocks. Blocks that a tree-sitter grammar parses as code become `code`
   events with a `language` attribute; everything else becomes `other`
   events with the line as `text`.

## Example

```python
--8<--
examples/mixed_content.py
--8<--
```

Output:

```text
--8<-- "examples/expected/mixed_content.txt"
```

The JSON route continued from line 2 through line 3, the fenced `log` block
went to the application-log parser, and the unfenced function was detected as
Python. Every event, whichever parser produced it, rebuilds exactly from the
aggregates.

## Configure the parser

| Argument | Purpose |
| --- | --- |
| `patterns` | Line patterns; replaces the default `log-level` pattern |
| `routes` | `(selector, parser)` pairs, tried in order |
| `fence_routes` | Parser for each lowercase fence language tag, such as `{"sql": SQLParser()}` |
| `code_languages` | Grammars used to detect unfenced code; `()` turns detection off |

Pattern and selector names must be unique, and `code`, `code_fence` and
`other` are reserved. Routed parsers that share a name must be the same
instance, and a parser cannot route to itself.

!!! note "Selectors decide, parsers interpret"

    A route selector should identify the format cheaply, for example
    `RegexPattern("json-line", r"^\{")`. The routed parser then does the real
    parsing, and its own patterns, statistics and evidence are kept. Fenced
    blocks are routed only by their declared language tag, never by guessing
    from their content.

## Capabilities and aggregation

`MixedContentParser` derives its capabilities from what you give it. It is
deterministic and parallel-safe only when every pattern and selector is a
`RegexPattern` or `ExactPattern` and every routed parser is deterministic and
parallel-safe. It is never partitionable, because fences, code blocks and
multi-line JSON span lines.

Aggregation is routed by parser: events of each routed parser are aggregated
with that parser's own aggregator, and the mixed-content parser's own events
(pattern, `code`, `fence` and `other` events) with its evidence aggregator.
The result's `pattern_statistics` count the lines adopted by each route under
the selector's name, the routed parser's own matches as `selector:pattern`,
the matches of each line pattern, and fenced (`code_fence`) and detected
(`code`) lines.

For a larger example that routes a custom SQL parser alongside the built-in
parsers over three files, see
[`mixed_custom_and_builtin.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/mixed_custom_and_builtin.py).
