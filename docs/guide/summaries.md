# Evidence summaries

`EvidenceSummarizer` turns evidence aggregates into a short natural-language
report with a language model, and checks every claim the model makes against
the evidence before it reaches you. The model never sees the raw input: it
reads facts derived from the aggregates, each with an identifier, counts and
line positions.

<figure class="diagram" markdown="span">
  ![Aggregates become facts with IDs, counts and lines, reviewed in parallel batches; the model drafts structured claims; deterministic checks validate IDs, totals and numbers; the model critiques the rendered report; issues or failed checks trigger revisions while revisions are left, otherwise SummaryValidationError; a clean report is rendered with exact counts and lines.](../assets/diagrams/summarization.png){ width="506" }
  <figcaption>Every batch is drafted, checked and critiqued before the
  report is rendered.</figcaption>
</figure>

## How a summary is produced

1. Aggregates are converted into **facts** with stable identifiers, and split
   into batches of at most `max_aggregates` aggregates. Batches are reviewed
   in parallel.
2. For each batch, the model drafts **structured claims** that cite fact
   identifiers.
3. **Deterministic checks** verify that every citation exists and that every
   count and number in a claim is supported by the cited facts.
4. The model **critiques** the rendered candidate against the facts.
5. Claims that fail a check or the critique are **revised**, up to
   `max_revisions` times. If a batch still fails, `SummaryValidationError` is
   raised; an unchecked report is never returned.
6. The final report is **rendered from the checked claims** without another
   model call. Counts and line positions come from the evidence, not from the
   model, and the report starts with an inventory of the severities recorded
   in the supplied evidence.

## Connect a model

`EvidenceSummarizer` talks to models through the `LanguageModel` ABC. A
model receives a sequence of `ChatMessage` objects, each with a `role` of
`"system"`, `"user"` or `"assistant"` and its `content`, and returns the
reply text. Subclass it to connect any provider:

```python
from collections.abc import Sequence

from parsefabric import ChatMessage, LanguageModel


class EchoModel(LanguageModel):
    """Replies with the last message; replace the body with a provider call."""

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        return messages[-1].content


print(EchoModel().name)
```

```text
EchoModel
```

`name` defaults to the class name and appears in error messages; override it
to identify the provider and model. ParseFabric never imports a provider
SDK, so the core package has no model dependencies.

[Language models](../extending/language-models.md) shows a model on the
official `openai` client and how to check a model with
`check_language_model`.

Any LangChain chat model works through
[`LangChainLanguageModel`](../integrations/langchain.md#language-models) from the
`langchain` extra.

## Summarize aggregates

<!-- docs-test: skip -->
```python
import asyncio
from pathlib import Path

from openai import AsyncOpenAI

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser
from parsefabric.summarization import EvidenceSummarizer


async def summarize(source: str) -> None:
    engine = ParseEngine()
    parser = ApplicationLogParser()
    result = await engine.parse(parser, source, ParseContext(source_id="checkout.log"))
    aggregates = await engine.aggregate(parser, result.events)

    async with AsyncOpenAI() as client:
        summarizer = EvidenceSummarizer(
            OpenAIModel(client, "gpt-5-mini"),
            task="Which failures happened, how often, and on which lines?",
            timeout=60,
        )
        summary = await summarizer.summarize(aggregates)
    print(summary.text)
    print(
        f"{summary.aggregates} aggregates, {summary.batches} batches, {summary.calls} model calls"
    )


asyncio.run(summarize(Path("checkout.log").read_text(encoding="utf-8")))
```

`summarize` returns an `EvidenceSummary` with the report `text` and the
number of `aggregates`, `batches` and model `calls`. To attach the report to
a parse result instead, use `summarize_result(result, aggregates)`, which
returns a copy of the result with the report in `llm_result`.

## Options

| Argument | Default | Meaning |
| --- | --- | --- |
| `task` | Summarize the most important errors and warnings, how often each occurred, and on which lines | The question the report answers |
| `max_aggregates` | 10 | Most aggregates sent to the model in one call; at least 2 |
| `max_concurrency` | `None` | Most batches reviewed at once; `None` reviews all batches in parallel |
| `max_revisions` | 2 | Most repair rounds per batch |
| `timeout` | `None` | Seconds allowed for each model call; `None` waits indefinitely |

Smaller batches keep each model call focused but need more calls. A batch
that passes on the first attempt takes two calls: one draft and one critique.

Batches run in an `asyncio.TaskGroup`. When one batch fails, batches that
have not called the model yet are cancelled, and the first failure is
raised. If the critic returns malformed output, it is asked again up to three
times without using a revision; after that `SummaryValidationError` is
raised.

## Model lifecycle

ParseFabric never opens or closes your model's resources. Create a client
inside the event loop that uses it and close it when you are done, as the
`async with AsyncOpenAI()` block above does. An application that calls
`asyncio.run` more than once, such as a Streamlit app on each rerun, should
create one client per run; the OpenAI-compatible example's `open_model()`
shows the pattern. Configure API keys through environment variables, never
in code.

The runnable examples read their configuration from environment variables:

| Example | Variables |
| --- | --- |
| [`llm_summary_openai_compatible.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/llm_summary_openai_compatible.py) | `PARSEFABRIC_LLM_API_KEY`, and optionally `PARSEFABRIC_LLM_BASE_URL` and `PARSEFABRIC_LLM_MODEL` |
| [`llm_summary.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/llm_summary.py) | `PARSEFABRIC_LLM_MODEL`, a LangChain `init_chat_model` identifier, plus the provider's API key variable |
| [`semantic_llm.py`](https://github.com/smuniharish/parsefabric/blob/main/examples/semantic_llm.py) | The same as the OpenAI-compatible example; a `SemanticParser` asks the model to interpret text, then the result is summarized |

## What the checks guarantee

- Every claim in the report cites facts that exist in the supplied evidence.
- Every count, total and number in a claim is supported by the cited facts,
  and the rendered counts and line positions are exact.
- A batch that cannot be repaired within `max_revisions` raises
  `SummaryValidationError` instead of returning unchecked text.

The model's critique judges whether claims faithfully describe the facts,
but it is a model judgment, not independent verification. The report covers
only the evidence you supply: a statement that no errors were recorded refers
to severity-labeled errors and warnings in those aggregates, not to every
possible problem. Review reports before acting on them in high-stakes
settings.
