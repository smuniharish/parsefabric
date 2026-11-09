# Language models

`EvidenceSummarizer` and `SemanticParser` call models through the
`LanguageModel` ABC, so ParseFabric never imports a provider SDK. Connect
any provider by subclassing it, or wrap a LangChain chat model with
[`LangChainLanguageModel`](../integrations/langchain.md#language-models).

Subclass `LanguageModel` and implement:

| Member | Contract |
| --- | --- |
| `async complete(messages)` | Send a sequence of `ChatMessage` objects and return the reply text |
| `name` | Optional: identifier used in logs and errors; defaults to the class name |

A `ChatMessage` has a `role` of `"system"`, `"user"` or `"assistant"` and
its `content`. The model owns transport concerns such as authentication,
retries and rate limits; callers own the overall time budget, such as
`EvidenceSummarizer(timeout=...)`. Create clients once and reuse them across
calls.

A model that answers from a fixed script, useful in tests:

```python
import asyncio
from collections.abc import Sequence

from parsefabric import ChatMessage, LanguageModel
from parsefabric.testing import check_language_model


class ScriptedModel(LanguageModel):
    """Return prepared replies in order; record every request."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.requests: list[tuple[ChatMessage, ...]] = []

    @property
    def name(self) -> str:
        return "scripted"

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.requests.append(tuple(messages))
        return self._replies.pop(0)


async def main() -> None:
    model = ScriptedModel("OK")
    print(await check_language_model(model))
    print([message.role for message in model.requests[0]])


asyncio.run(main())
```

```text
OK
['system', 'user']
```

`check_language_model(model)` sends one short system and user conversation
and checks that the reply is non-empty text. Run it against a live model in
an integration test.

A model on the official `openai` client:

<!-- docs-test: skip -->
```python
from collections.abc import Sequence

from openai import AsyncOpenAI

from parsefabric import ChatMessage, LanguageModel


class OpenAIModel(LanguageModel):
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return response.choices[0].message.content or ""
```

Pass the model to `EvidenceSummarizer(model)` to
[summarize aggregates](../guide/summaries.md), or to a
[`SemanticParser`](parsers.md#parsers-that-call-services-or-models).
