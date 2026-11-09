# Command output backends

`CLIOutputParser(command=...)` turns the complete output of a command into
records with a `CommandOutputBackend`. The default `JcBackend` uses the
[jc](https://github.com/kellyjonbrazil/jc) parsers. Write your own to parse
output of commands jc does not know, or to call another library or service.

Subclass `CommandOutputBackend` and implement:

| Member | Contract |
| --- | --- |
| `name` | Backend name used in messages, such as `"jc"` |
| `validate(command)` | Raise `ValueError` if the backend cannot parse the output of `command`; called when the parser is created |
| `async parse(command, text)` | Return a JSON object or a list of JSON objects, one per record; raise for output the backend cannot parse |

The parser turns each record into a `cli_record` event, and an exception
from `parse` into an `unparsed` event plus a `ParseIssue`. Pass the backend
as `CLIOutputParser(command=..., backend=...)`.

A backend for `key=value` lines, such as the output of `env`:

```python
import asyncio

from parsefabric import ParseEngine
from parsefabric.builtins import CLIOutputParser, CommandOutputBackend
from parsefabric.testing import check_command_output_backend


class KeyValueBackend(CommandOutputBackend):
    """Parse `key=value` lines into one record per line."""

    @property
    def name(self) -> str:
        return "key-value"

    def validate(self, command: str) -> None:
        if command not in {"env", "printenv"}:
            raise ValueError(f"key-value cannot parse {command!r} output")

    async def parse(self, command: str, text: str) -> object:
        records = []
        for line in text.splitlines():
            if line.strip():
                key, separator, value = line.partition("=")
                if not separator:
                    raise ValueError(f"expected key=value, got {line!r}")
                records.append({"key": key, "value": value})
        return records


async def main() -> None:
    output = "HOME=/home/app\nLANG=C.UTF-8\n"
    print(await check_command_output_backend(KeyValueBackend(), "env", output))
    parser = CLIOutputParser(command="env", backend=KeyValueBackend())
    result = await ParseEngine().parse(parser, "HOME=/home/app\nbroken line\n")
    print([event.event_type for event in result.events], len(result.errors))


asyncio.run(main())
```

```text
({'key': 'HOME', 'value': '/home/app'}, {'key': 'LANG', 'value': 'C.UTF-8'})
['unparsed'] 1
```

`check_command_output_backend(backend, command, output)` checks that the
backend names itself, accepts `command`, and turns `output` into records
that `CLIOutputParser` reports without issues; it returns the records.
