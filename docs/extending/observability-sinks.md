# Observability sinks

A sink receives the lifecycle events of parsing, aggregation, partitioning
and execution. ParseFabric ships sinks that discard events (the default),
log them with structlog, record OpenTelemetry spans, and fan out to several
sinks. Write your own to feed metrics, a message queue or another tracing
system.

Subclass `ObservabilitySink` and implement:

| Member | Contract |
| --- | --- |
| `async emit(event)` | Record one `LifecycleEvent`; keep it fast, because callers await it inline |
| `async flush()` | Optional: deliver buffered events |
| `async close()` | Optional: flush and release connections; call it when your application shuts down |

A `LifecycleEvent` has a `name` such as `ParseStarted`, an optional
`parser_name` and `partition_id`, scalar `attributes` and an `occurred_at`
timestamp. An exception raised by a sink is logged on the
`parsefabric.observability` logger and never fails the operation being
observed. Custom backends and partitioners publish events with
`ExecutionBackend.emit` or `parsefabric.observability.publish`, which apply
the same rule.

Pass a sink to `ParseEngine`, to backends as `sink=`, and to
`LinePartitioner(sink=)`:

```python
import asyncio
from collections import Counter

from parsefabric import ParseEngine
from parsefabric.builtins import ApplicationLogParser
from parsefabric.observability import (
    CompositeObservabilitySink,
    LifecycleEvent,
    ObservabilitySink,
    OpenTelemetryObservabilitySink,
)
from parsefabric.testing import check_observability_sink


class CountingSink(ObservabilitySink):
    """Count lifecycle events by name."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    async def emit(self, event: LifecycleEvent) -> None:
        self.counts[event.name] += 1


async def main() -> None:
    await check_observability_sink(CountingSink())
    counting = CountingSink()
    sink = CompositeObservabilitySink([counting, OpenTelemetryObservabilitySink()])
    engine = ParseEngine(sink)
    inputs = ["db timeout", "all good", b"\xff"]
    async for _ in engine.parse_iter(ApplicationLogParser(), inputs, continue_on_error=True):
        pass
    await sink.close()
    print(dict(sorted(counting.counts.items())))


asyncio.run(main())
```

```text
{'ParseCompleted': 2, 'ParseFailed': 1, 'ParseStarted': 3, 'ParserSelected': 3, 'PatternMatched': 1}
```

`check_observability_sink(sink)` sends events with and without attributes,
then flushes and closes the sink; it fails if the sink raises.
