# LangChain and LangGraph

The `langchain` extra adapts ParseFabric to LangChain and LangGraph. The
core package never imports either framework.

```bash
pip install "parsefabric[langchain]"
```

Everything lives in `parsefabric.integrations.langchain`.

## Language models

`LangChainLanguageModel` wraps any LangChain `BaseLanguageModel`, such as a
chat model from `init_chat_model`, as a ParseFabric `LanguageModel`.
`ChatMessage` roles map to system, human and AI messages, and the reply is
returned as text:

<!-- docs-test: skip -->
```python
from langchain.chat_models import init_chat_model

from parsefabric.integrations.langchain import LangChainLanguageModel
from parsefabric.summarization import EvidenceSummarizer

model = LangChainLanguageModel(init_chat_model("openai:gpt-5-mini"))
summarizer = EvidenceSummarizer(model)
```

The model's `name` is `langchain:<class name>`.

## Parsers as agent tools

`parser_tool(parser)` returns an async LangChain `StructuredTool`. The tool
takes `text` and an optional `source_id` and returns the parse result as a
JSON object, so an agent can parse text and cite the evidence it received.
The tool is named `parse_<parser name>` unless you pass `name`, and
`description` overrides the generated description. Pass `engine` to share a
configured `ParseEngine`.

## Parsers as graph nodes

`parser_node(parser)` returns an async LangGraph node. It reads the text
from `input_key` (default `"text"`), optionally the source identifier from
`source_id_key`, and writes the `ParseResult` to `output_key` (default
`"parse_result"`).

```python
import asyncio

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from parsefabric import ParseResult
from parsefabric.builtins import ApplicationLogParser
from parsefabric.integrations.langchain import parser_node, parser_tool


class State(TypedDict, total=False):
    text: str
    parse_result: ParseResult


async def main() -> None:
    graph = StateGraph(State)  # type: ignore[bad-specialization]
    graph.add_node("parse", parser_node(ApplicationLogParser()))
    graph.add_edge(START, "parse")
    graph.add_edge("parse", END)
    log = "2026-10-01T08:00:02Z ERROR database timeout\n"
    state = await graph.compile().ainvoke({"text": log})
    print(len(state["parse_result"].events), "events")

    tool = parser_tool(ApplicationLogParser())
    output = await tool.ainvoke({"text": log, "source_id": "service.log"})
    print(tool.name, "returned", len(output["events"]), "events")


asyncio.run(main())
```

```text
2 events
parse_application_log returned 2 events
```

[`langchain_agent.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/langchain_agent.py)
combines both in a graph that parses a log and counts error lines.
