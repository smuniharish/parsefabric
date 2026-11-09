"""Summarize parsed evidence with an OpenAI-compatible endpoint.

Requires the ``openai`` and ``sqlglot`` packages (``uv sync --group examples``
in a checkout). Configure the endpoint through environment variables only;
never hard-code an API key:

    PARSEFABRIC_LLM_API_KEY   required
    PARSEFABRIC_LLM_BASE_URL  optional, OpenAI-compatible ``/v1`` base URL
    PARSEFABRIC_LLM_MODEL     optional, default ``gpt-5-mini``

Run: python examples/llm_summary_openai_compatible.py

``OpenAICompatibleModel`` shows how little a `LanguageModel` needs: one async
``complete`` method. The model reads evidence facts derived from aggregates.
The example summarizes the same incident twice: once with the default batch
size and once with ``max_aggregates=2``. Each batch requires structured
drafting and grounded critique, with bounded repair on rejection. Final
rendering is deterministic; successful first attempts use two calls per batch.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, override

from llm_summary import summarize_incident

from parsefabric.llm import ChatMessage, LanguageModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from openai import AsyncOpenAI
    from openai.types.chat import ChatCompletionMessageParam

DEFAULT_MODEL = "gpt-5-mini"


def _openai_message(message: ChatMessage) -> ChatCompletionMessageParam:
    match message.role:
        case "system":
            return {"role": "system", "content": message.content}
        case "user":
            return {"role": "user", "content": message.content}
        case "assistant":
            return {"role": "assistant", "content": message.content}


class OpenAICompatibleModel(LanguageModel):
    """A `LanguageModel` that calls an OpenAI-compatible chat completions API."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model

    @property
    @override
    def name(self) -> str:
        return f"openai:{self.model}"

    @override
    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[_openai_message(message) for message in messages],
        )
        return response.choices[0].message.content or ""

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self.client.close()


def build_model() -> OpenAICompatibleModel | None:
    """Return the configured model, or None when no API key is set."""
    api_key = os.environ.get("PARSEFABRIC_LLM_API_KEY")
    if not api_key:
        return None
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=os.environ.get("PARSEFABRIC_LLM_BASE_URL") or None,
        timeout=120,
        max_retries=2,
    )
    return OpenAICompatibleModel(client, os.environ.get("PARSEFABRIC_LLM_MODEL", DEFAULT_MODEL))


@asynccontextmanager
async def open_model() -> AsyncGenerator[LanguageModel | None]:
    """Yield the configured model and close its HTTP client on exit."""
    model = build_model()
    try:
        yield model
    finally:
        if model is not None:
            await model.aclose()


async def run(model: LanguageModel) -> None:
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
            print("Set PARSEFABRIC_LLM_API_KEY (and optionally PARSEFABRIC_LLM_BASE_URL,")
            print("PARSEFABRIC_LLM_MODEL) to run against an OpenAI-compatible endpoint.")
            return
        await run(model)


def main() -> None:
    asyncio.run(run_configured())


if __name__ == "__main__":
    main()
