"""Build a line parser from regex, exact-value and predicate patterns.

Run: python examples/custom_patterns.py
"""

import asyncio
import re

from parsefabric import DeterministicParser, ParseContext, ParseEngine
from parsefabric.patterns import ExactPattern, PredicatePattern, RegexPattern

DEPLOY_LOG = """\
deploy web-7 started
health check passed in 120 ms
health check failed in 2400 ms
ROLLBACK
deploy web-7 finished
"""

_LATENCY = re.compile(r"in (\d+) ms$")


def is_slow(value: object) -> bool:
    """Whether a health check took longer than one second."""
    found = _LATENCY.search(value) if isinstance(value, str) else None
    return found is not None and int(found.group(1)) > 1000


def latency(value: object) -> dict[str, int]:
    found = _LATENCY.search(value) if isinstance(value, str) else None
    return {"latency_ms": int(found.group(1))} if found else {}


def build_parser(*, first_match_only: bool = False) -> DeterministicParser:
    return DeterministicParser(
        [
            RegexPattern(
                "deploy",
                r"^deploy (?P<service>\S+) (?P<state>started|finished)$",
                event_type="deployment",
            ),
            RegexPattern(
                "health",
                r"^health check (?P<outcome>passed|failed)",
                event_type="health_check",
            ),
            ExactPattern(
                "rollback",
                "ROLLBACK",
                event_type="rollback",
                severity="ERROR",
                attributes={"action": "rollback"},
            ),
            PredicatePattern("slow", is_slow, latency, priority=10, severity="WARNING"),
        ],
        name="deploy-log",
        first_match_only=first_match_only,
    )


async def main() -> None:
    engine = ParseEngine()
    context = ParseContext(source_id="deploy.log")
    parser = build_parser()
    print("patterns in evaluation order:", [p.name for p in parser.patterns])
    result = await engine.parse(parser, DEPLOY_LOG, context)
    for event in result.events:
        print(
            f"line {event.evidence.line_number}: {event.event_type:<12} "
            f"severity={event.severity} attributes={event.attributes}"
        )
    print("matches:", {s.pattern_name: s.matches for s in result.pattern_statistics})

    first_only = await engine.parse(
        build_parser(first_match_only=True), DEPLOY_LOG, context
    )
    print("events with first_match_only:", len(first_only.events))

    parser.register_pattern(
        RegexPattern("finished", r"finished$", event_type="completion", priority=5)
    )
    extended = await engine.parse(parser, DEPLOY_LOG, context)
    print("events after register_pattern:", len(extended.events))


if __name__ == "__main__":
    asyncio.run(main())
