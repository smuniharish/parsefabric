# Code detectors

`MixedContentParser` asks a `CodeDetector` whether lines that no route or
pattern claims are source code, and in which language. The default
`TreeSitterCodeDetector` tries tree-sitter grammars. Write your own to use a
classifier model, a service, or rules for the languages your logs contain.

Subclass `CodeDetector` and implement:

| Member | Contract |
| --- | --- |
| `async detect(text)` | Return the language name of a block of text, or `None` if it is not code; return the same answer for the same text |
| `async prepare()` | Optional: load models or grammars ahead of the first detection |

Pass the detector as `MixedContentParser(code_detector=...)`, or
`code_detector=None` to turn detection off. Offload slow detection with
`asyncio.to_thread`.

A detector for SQL statements and shell prompts:

```python
import asyncio
import re

from parsefabric import ParseEngine
from parsefabric.builtins import CodeDetector, MixedContentParser
from parsefabric.testing import check_code_detector

RULES = (
    ("sql", re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)),
    ("shell", re.compile(r"^\s*\$ \S")),
)


class RuleCodeDetector(CodeDetector):
    """Detect code with one regular expression per language."""

    async def detect(self, text: str) -> str | None:
        for language, rule in RULES:
            if rule.match(text):
                return language
        return None


async def main() -> None:
    await check_code_detector(
        RuleCodeDetector(),
        {"SELECT 1": "sql", "$ ls -la": "shell", "the payment failed": None},
    )
    parser = MixedContentParser(code_detector=RuleCodeDetector())
    text = "query failed:\nSELECT id FROM orders WHERE total > 10\n"
    result = await ParseEngine().parse(parser, text)
    for event in result.events:
        print(event.event_type, event.attributes.get("language"))


asyncio.run(main())
```

```text
other None
code sql
```

`check_code_detector(detector, expected)` checks that each sample is
detected as the expected language, or `None`, and that repeating a sample
repeats the answer.
