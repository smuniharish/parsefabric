# Integrations

ParseFabric's core depends on no framework. Integrations connect it to the
tools around it:

| Page | Connects ParseFabric to |
| --- | --- |
| [LangChain and LangGraph](langchain.md) | LangChain chat models as `LanguageModel`s, parsers as agent tools and graph nodes; install the `langchain` extra |
| [Distributed runtimes](distributed-runtimes.md) | Celery, Apache Spark and Apache Flink, through custom execution backends and batch jobs |

For OpenTelemetry tracing, see [Observability](../guide/observability.md#export-traces).
