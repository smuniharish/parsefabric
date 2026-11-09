# The parsefabric-extend skill

The [`parsefabric-extend`](https://github.com/smuniharish/parsefabric/tree/main/parsefabric-skills/skills/parsefabric-extend) skill guides an agent that
extends ParseFabric by subclassing one of its abstract base classes. It loads
for tasks such as "write a parser for our vendor audit format" or "send
lifecycle events to Kafka", and hands over to the `parsefabric` skill when
the built-in components are enough.

## What it teaches

- Choosing the right abstract base class, its default implementation, and
  where an instance is passed. See [Extending ParseFabric](../extending/index.md).
- Implementing every abstract method as declared, with coroutines for work
  that may do I/O.
- Declaring only the parser capabilities the parser really has, and keeping
  evidence on every event.
- Proving the extension with the matching `parsefabric.testing` contract
  check.

## Files

| File | Read or run it when |
| --- | --- |
| [`SKILL.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/SKILL.md) | Always: the workflow, rules and gotchas. |
| [`references/extension-points.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/references/extension-points.md) | Choosing an abstract base class. |
| [`references/parsers-and-aggregators.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/references/parsers-and-aggregators.md) | Writing a parser, pattern or aggregator. |
| [`references/runtime-components.md`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/references/runtime-components.md) | Writing a codec, partitioner, backend, sink, language model, tokenizer, detector or registry. |
| [`scripts/check_extension.py`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/scripts/check_extension.py) | Detects which abstract base class an extension subclasses and runs its contract check. |
| [`assets/parser_template.py`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/assets/parser_template.py) and [`assets/test_parser.py`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/assets/test_parser.py) | Starting a parser and its tests. |
| [`assets/sink_template.py`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/assets/sink_template.py) and [`assets/test_sink.py`](https://github.com/smuniharish/parsefabric/blob/main/parsefabric-skills/skills/parsefabric-extend/assets/test_sink.py) | Starting an observability sink and its tests. |

## Check an extension

```bash
python scripts/check_extension.py my_parsers:VendorAuditParser --input sample.log
python scripts/check_extension.py my_patterns:DISK_FULL --matching "disk full" --other "disk ok"
python scripts/check_extension.py my_sinks:KafkaSink --json
```

The argument is `MODULE:NAME`, where `NAME` is an instance or a factory that
returns one. Exit code 0 means the contract holds, 1 names the broken
promise, and 2 means the extension could not be loaded or an input is
missing.
