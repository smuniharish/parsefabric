"""Summarize parsed evidence with an OpenAI-compatible endpoint.

Requires ``pip install "parsefabric[openai]" sqlglot`` (or ``uv sync`` in a
checkout). Configure the endpoint through environment variables only; never
hard-code an API key:

    PARSEFABRIC_LLM_API_KEY   required
    PARSEFABRIC_LLM_BASE_URL  optional, OpenAI-compatible ``/v1`` base URL
    PARSEFABRIC_LLM_MODEL     optional, default ``gpt-5-mini``

Run: python examples/llm_summary_openai_compatible.py

The model reads evidence facts derived from aggregates. The example summarizes
the same incident twice: once with the default batch size and once with
``max_aggregates=2``. Each batch requires structured drafting and grounded
critique, with bounded repair on rejection. Final rendering is deterministic;
successful first attempts use two calls per batch, with no synthesizer.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.language_models import BaseChatModel
from llm_summary import summarize_incident

DEFAULT_MODEL = "gpt-5-mini"


def build_model() -> BaseChatModel | None:
    """Return the configured model, or None when no API key is set."""
    api_key = os.environ.get("PARSEFABRIC_LLM_API_KEY")
    if not api_key:
        return None
    from langchain_openai import ChatOpenAI
    from openai import DefaultAsyncHttpxClient

    # langchain-openai shares one async HTTP client per process by default. A
    # client owned by this model is never reused from a closed event loop.
    return ChatOpenAI(
        model=os.environ.get("PARSEFABRIC_LLM_MODEL", DEFAULT_MODEL),
        base_url=os.environ.get("PARSEFABRIC_LLM_BASE_URL") or None,
        api_key=api_key,
        timeout=120,
        max_retries=2,
        http_async_client=DefaultAsyncHttpxClient(),
    )


@asynccontextmanager
async def open_model() -> AsyncIterator[BaseChatModel | None]:
    """Yield the configured model and close its HTTP client on exit."""
    model = build_model()
    try:
        yield model
    finally:
        client = getattr(model, "http_async_client", None)
        if client is not None:
            await client.aclose()


async def run(model: BaseChatModel) -> None:
    for max_aggregates in (10, 2):
        summary = await summarize_incident(model, max_aggregates=max_aggregates)
        print(f"--- max_aggregates={max_aggregates}")
        print(
            f"{summary.aggregates} aggregates in {summary.batches} batches, "
            f"{summary.calls} model calls"
        )
        print(summary.text)


async def run_configured() -> None:
    async with open_model() as model:
        if model is None:
            print(
                "Set PARSEFABRIC_LLM_API_KEY (and optionally PARSEFABRIC_LLM_BASE_URL,"
            )
            print(
                "PARSEFABRIC_LLM_MODEL) to run against an OpenAI-compatible endpoint."
            )
            return
        await run(model)


def main() -> None:
    asyncio.run(run_configured())


if __name__ == "__main__":
    main()
