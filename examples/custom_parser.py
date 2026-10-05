"""Write an application-defined parser, register it and aggregate its events.

Run: python examples/custom_parser.py
"""

import asyncio

from parsefabric import ParseContext, ParsedEvent, ParseEngine, ParseResult
from parsefabric.parser import SemanticParser
from parsefabric.registry import ParserRegistry

TICKETS = (
    "How do I reset my password?",
    "The invoice total is wrong.",
    "Can I change my delivery address?",
)


class IntentParser(SemanticParser):
    """Label support messages as questions or reports.

    A real semantic parser would call a model or service here; the contract is
    the same: return a ``ParseResult`` with events.
    """

    def __init__(self) -> None:
        super().__init__(name="ticket-intent", version="2")

    async def parse(
        self, source: object, context: ParseContext | None = None
    ) -> ParseResult:
        if not isinstance(source, str):
            raise TypeError("ticket text must be a string")
        label = "question" if source.rstrip().endswith("?") else "report"
        return ParseResult(
            events=(ParsedEvent("intent", {"label": label, "text": source}),),
            parser_name=self.name,
            parser_version=self.version,
        )


async def main() -> None:
    registry = ParserRegistry()
    registry.register(IntentParser())
    metadata = registry.metadata("ticket-intent")
    print(
        f"registered {metadata.name} v{metadata.version} ({metadata.parser_type}),",
        f"deterministic={metadata.capabilities.deterministic}",
    )

    parser = registry.get("ticket-intent")
    engine = ParseEngine()
    context = ParseContext(source_id="tickets")
    events = []
    async for result in engine.parse_iter(parser, TICKETS, context=context):
        events.extend(result.events)
    for event in events:
        print(f"{event.attributes['label']:<9} {event.attributes['text']}")

    (aggregate,) = await engine.aggregate(parser, events)
    print("aggregate retains events:", aggregate.retains_events)
    restored = await engine.materialize(parser, None, (aggregate,))
    print("materialized without the source:", restored == tuple(events))


if __name__ == "__main__":
    asyncio.run(main())
