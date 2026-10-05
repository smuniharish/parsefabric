"""Versioned, allowlisted mixed-content fixture shared by runtime examples."""

from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    MixedContentParser,
)
from parsefabric.patterns import RegexPattern

MIXED_SOURCE = (
    'ERROR database timeout\n{"status":"ok"}\nMETRIC load: 42\n'
    "```python\nprint('hello')\n```\nunknown note"
)


def mixed_parser() -> MixedContentParser:
    """Build the same deterministic parser on driver and workers."""
    return MixedContentParser(
        routes=[
            (RegexPattern("log-line", r"^ERROR\b"), ApplicationLogParser()),
            (RegexPattern("json-line", r"^\{"), JSONParser()),
            (
                RegexPattern("metric-line", r"^METRIC\b"),
                CLIOutputParser(
                    [
                        RegexPattern(
                            "metric",
                            r"^METRIC (?P<name>\w+): (?P<value>\d+)",
                        )
                    ],
                    name="metrics",
                ),
            ),
        ]
    )
