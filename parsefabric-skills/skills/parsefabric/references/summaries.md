# Checked summaries and language models

Read this when a language model should summarize parsed evidence, or
interpret text a deterministic parser cannot. The full guide is
[Evidence summaries](https://parsefabric.readthedocs.io/en/latest/guide/summaries/).

## Summarize aggregates

<!-- docs-test: skip -->
```python
from parsefabric.summarization import EvidenceSummarizer

summarizer = EvidenceSummarizer(
    model,  # a LanguageModel
    task="Which failures happened, how often, and on which lines?",
    timeout=60,
)
summary = await summarizer.summarize(aggregates)
print(summary.text, summary.calls)
```

- The model never sees the raw input, only facts derived from the
  aggregates, each with an identifier, counts and line positions.
- Every claim must cite existing facts, and every number must be supported
  by them; counts and lines in the report come from the evidence.
- A batch that cannot be repaired within `max_revisions` (default 2) raises
  `SummaryValidationError`. Never catch it to return the draft instead.
- `summarize_result(result, aggregates)` returns a copy of the result with
  the report in `llm_result`.

| Option | Default |
| --- | --- |
| `max_aggregates` | 10 per model call, at least 2 |
| `max_concurrency` | `None`: all batches in parallel |
| `max_revisions` | 2 |
| `timeout` | `None`: seconds per model call |

## Connect a model

`LanguageModel` is an ABC with one coroutine,
`complete(messages) -> str`, where each `ChatMessage` has a `role`
(`"system"`, `"user"` or `"assistant"`) and `content`.

- Any LangChain chat model:
  `LangChainLanguageModel(init_chat_model("openai:gpt-5-mini"))` from
  `parsefabric.integrations.langchain`, with `pip install "parsefabric[langchain]"`.
- Any other provider: subclass `LanguageModel`; the parsefabric-extend
  skill covers that.

ParseFabric never opens or closes the model's client. Create the client
inside the event loop that uses it, close it when done, and read API keys
from environment variables.

## LangChain tools and LangGraph nodes

- `parser_tool(parser)` returns an async `StructuredTool` named
  `parse_<parser name>`, taking `text` and an optional `source_id`.
- `parser_node(parser)` returns an async LangGraph node that reads
  `input_key` (default `"text"`) and writes the `ParseResult` to
  `output_key` (default `"parse_result"`).

Both are in `parsefabric.integrations.langchain`. LangGraph itself is the
application's dependency.

## Model-backed parsing

`SemanticParser` subclasses, constructed with `name=`, `version=` and
`model=`, let a model interpret text. They are not
deterministic, so their aggregates retain every event. Treat their events as
model output and review them before acting on them.
