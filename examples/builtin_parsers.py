"""Parse JSON, a Python traceback, command output and a timestamped log.

Run: python examples/builtin_parsers.py
"""

import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import (
    CLIOutputParser,
    JSONParser,
    PythonTracebackParser,
    TimestampedLogParser,
)

TRACEBACK = """\
Traceback (most recent call last):
  File "worker.py", line 18, in run
    response = gateway.charge(order)
  File "gateway.py", line 42, in charge
    raise TimeoutError("upstream request expired")
TimeoutError: upstream request expired
"""

DF_OUTPUT = """\
Filesystem     1K-blocks     Used Available Use% Mounted on
/dev/sda1       20509264 13424508   6015900  70% /
/dev/sdb1      103081248 97929176   5152072  96% /var/lib/data
"""

OPERATIONS_LOG = """\
2026-10-01T08:00:03+00:00 ERROR shop database timeout
2026-10-01T08:00:05+00:00 INFO retry scheduled with a fresh connection
2026-10-01T08:00:07+00:00 INFO 22 orders reconciled
"""


async def main() -> None:
    engine = ParseEngine()

    order = await engine.parse(
        JSONParser(), '{"order": 1042, "status": "paid", "total": 99.5}'
    )
    print("json:", order.events[0].event_type, order.events[0].attributes["value"])

    invalid = await engine.parse(JSONParser(), '{"order": 1042,')
    print("invalid json:", invalid.events[0].event_type, invalid.errors[0].error_type)

    (failure,) = (await engine.parse(PythonTracebackParser(), TRACEBACK)).events
    frames = failure.attributes["frames"]
    print(
        "traceback:",
        failure.attributes["exception_type"],
        "-",
        failure.attributes["message"],
        f"({len(frames) if isinstance(frames, list) else 0} frames)",
    )

    disks = await engine.parse(CLIOutputParser(command="df"), DF_OUTPUT)
    for event in disks.events:
        print(
            "df:",
            event.attributes["mounted_on"],
            f"{event.attributes['use_percent']}% used",
        )

    log = await engine.parse(
        TimestampedLogParser(), OPERATIONS_LOG, ParseContext(source_id="ops.log")
    )
    for event in log.events:
        time = event.timestamp.time().isoformat() if event.timestamp else "-"
        print(
            f"log line {event.evidence.line_number}:",
            time,
            event.severity,
            event.attributes["message"],
        )


if __name__ == "__main__":
    asyncio.run(main())
