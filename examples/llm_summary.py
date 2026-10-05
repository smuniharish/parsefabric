"""Summarize parsed evidence with any LangChain chat model.

The model reads facts derived from aggregates, never the raw log. Lines are
routed to the timestamped-log, SQL, JSON and metric parsers of
``mixed_custom_and_builtin.py``, so every evidence entry carries a meaningful
message for the model to reason about.

Requires ``langchain``, ``sqlglot`` and the provider's LangChain integration
package. Set ``PARSEFABRIC_LLM_MODEL`` to an ``init_chat_model`` identifier such
as ``openai:gpt-5-mini`` and configure the provider's API key.

Run: python examples/llm_summary.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from langchain_core.language_models import BaseLanguageModel
from mixed_custom_and_builtin import make_parser

from parsefabric import ParseContext
from parsefabric.summarization import EvidenceSummarizer, EvidenceSummary

SOURCE = Path(__file__).with_name("data") / "mixed-shop-incident.txt"


async def summarize_incident(
    model: BaseLanguageModel, *, max_aggregates: int = 10
) -> EvidenceSummary:
    parser = make_parser(timestamped=True)
    source = SOURCE.read_text(encoding="utf-8")
    result = await parser.parse(source, ParseContext(source_id=SOURCE.name))
    aggregates = await parser.aggregate(result.events)
    summarizer = EvidenceSummarizer(
        model,
        max_aggregates=max_aggregates,
        task="Which failures happened, how often, and on which lines?",
    )
    return await summarizer.summarize(aggregates)


def main() -> None:
    identifier = os.environ.get("PARSEFABRIC_LLM_MODEL")
    if not identifier:
        print("Set PARSEFABRIC_LLM_MODEL (for example openai:gpt-5-mini) to run.")
        return
    from langchain.chat_models import init_chat_model

    summary = asyncio.run(summarize_incident(init_chat_model(identifier)))
    print(f"{summary.aggregates} aggregates in {summary.batches} batches")
    print(f"{summary.calls} model calls")
    print(summary.text)


if __name__ == "__main__":
    main()
