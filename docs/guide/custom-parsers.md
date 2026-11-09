# Patterns and custom parsers

When the [built-in parsers](builtin-parsers.md) do not fit your format, build
a parser from patterns, or write a parser class of your own. Either way, the
package manages aggregation and serialization, so your events get the same
lossless storage as the built-in ones.

## Patterns

A pattern is a named, prioritized rule that recognizes one kind of value and
turns a match into an event. Every pattern accepts `priority` (higher runs
first), `event_type` (defaults to the name) and `metadata` (free-form notes
that are never copied into events).

| Pattern | Matches | Event attributes |
| --- | --- | --- |
| `RegexPattern(name, expression)` | Text that the regular expression finds anywhere (`re.search`) | The named groups that took part in the match |
| `ExactPattern(name, expected)` | Values equal to `expected` | The fixed `attributes` you supply |
| `PredicatePattern(name, predicate, extractor)` | Values for which `predicate(value)` is true | `extractor(value)`, or none |
| `StructuredPattern(name, predicate, extractor)` | Mappings, such as decoded JSON objects, for which `predicate` is true | `extractor(mapping)`, or the mapping itself |

`RegexPattern`, `ExactPattern`, `PredicatePattern` and `StructuredPattern`
also accept a `severity` for the events they produce.

!!! tip "Write linear-time regular expressions"

    Patterns run on untrusted input, and Python regular expressions have no
    timeout. Anchor expressions with `^` when they describe a whole line, and
    avoid nested or overlapping quantifiers such as `(a+)+` or `.*x.*y`.

## Build a parser from patterns

`DeterministicParser` applies a set of patterns to every line of a text
document. Each line is matched against every pattern in descending priority
order (ties broken by name); each match becomes one event whose evidence
records the line number, the line's byte span and the pattern name. With
`first_match_only=True`, only the first matching pattern on each line
produces an event.

```python
--8<--
examples/custom_patterns.py
--8<--
```

Output:

```text
--8<-- "examples/expected/custom_patterns.txt"
```

`register_pattern` adds a pattern, or replaces one with the same name when
you pass `replace=True`; `unregister_pattern` removes one. The result's
`pattern_statistics` count the matches of every pattern, including those that
never matched.

A `DeterministicParser` is deterministic, aggregatable, parallel-safe and
line-partitionable by default. If a `PredicatePattern` callable is not
thread-safe, pass explicit `capabilities` without `parallel_safe`. A
`DeterministicParser` must stay deterministic; put non-reproducible logic in
a [parser class](#write-a-parser-class) instead.

## Capabilities

Every parser declares `ParserCapabilities`, and orchestration code checks them
before scheduling work:

| Capability | Promise | Checked by |
| --- | --- | --- |
| `deterministic` | The same input and context always produce the same result | Aggregation: deterministic, stateless parsers store line positions instead of events |
| `parallel_safe` | One instance may parse several inputs concurrently | `parse_async_iter` with `max_concurrency` above 1 |
| `partitionable`, `partition_framing` | A document may be split, for example by `"line"`, and its chunks parsed independently | `LinePartitioner` |
| `stateful` | Results depend on earlier inputs | Aggregation: stateful parsers retain their events |
| `requires_order` | Inputs must be parsed in order | Cannot be combined with `parallel_safe` |
| `aggregatable` | Events may be aggregated | `ParseEngine.aggregate` and `merge_aggregates` raise `CapabilityError` otherwise |

Unsafe combinations are rejected when the capabilities are created: a
partitionable parser must be deterministic, parallel-safe, stateless and
order-independent and must declare its framing, and a stateful or
order-dependent parser cannot be parallel-safe.

## Write a parser class

For formats that are not line-by-line pattern matching, subclass `Parser`,
`AsyncParser` or `SemanticParser`; see [Parsers](../extending/parsers.md).
To keep and look up parsers by name, or to publish them as plugins, see
[Parser registries](../extending/registries.md).
