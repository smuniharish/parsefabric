"""Use ParseFabric parsers as LangChain tools and LangGraph nodes.

Requires ``parsefabric[langchain]`` and ``langgraph``. No model or API key is
needed: the graph parses text in one node and counts errors in the next, and
the tool is invoked directly, as an agent would call it.

Run: python examples/langchain_agent.py
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from parsefabric.builtins import ApplicationLogParser
from parsefabric.integrations.langchain import parser_node, parser_tool
from parsefabric.models import ParseResult

LOG = (
    "2026-10-01T08:00:00Z INFO service started\n"
    "2026-10-01T08:00:02Z ERROR database timeout\n"
    "2026-10-01T08:00:05Z ERROR database timeout\n"
)


class IncidentState(TypedDict, total=False):
    text: str
    source_id: str
    parse_result: ParseResult
    error_lines: tuple[int | None, ...]


def count_errors(state: IncidentState) -> IncidentState:
    # One line can match several patterns, so count distinct source lines.
    lines = {
        event.evidence.line_number
        for event in state["parse_result"].events
        if event.severity == "ERROR" and event.evidence is not None
    }
    return {"error_lines": tuple(sorted(lines, key=lambda line: line or 0))}


async def run_graph(text: str) -> dict[str, Any]:
    # pyrefly does not match TypedDict states against LangGraph's StateT bound.
    # pyrefly: ignore[bad-specialization]
    graph = StateGraph(IncidentState)
    graph.add_node("parse", parser_node(ApplicationLogParser(), source_id_key="source_id"))
    graph.add_node("count", count_errors)
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "count")
    graph.add_edge("count", END)
    return await graph.compile().ainvoke({"text": text, "source_id": "service.log"})


async def main() -> None:
    state = await run_graph(LOG)
    events = len(state["parse_result"].events)
    print(f"graph: {events} events, error lines {list(state['error_lines'])}")
    tool = parser_tool(ApplicationLogParser())
    output = await tool.ainvoke({"text": LOG, "source_id": "service.log"})
    serialized = output["events"]
    if not isinstance(serialized, list):
        raise TypeError("the tool returns serialized events")
    print(f"tool {tool.name}: {len(serialized)} events")


if __name__ == "__main__":
    asyncio.run(main())
