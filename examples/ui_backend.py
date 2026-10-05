"""Parser configuration and execution for the local Streamlit playground."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from custom_sql import SQLStatementParser
from langchain_core.language_models import BaseLanguageModel
from mixed_custom_and_builtin import _BRACKETED_LOG, make_parser

from parsefabric.aggregation import EvidenceAggregate
from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    JSONParser,
    MixedContentParser,
    TimestampedLogParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import ConfigurationError, ParseError
from parsefabric.models import ParseContext, ParseResult
from parsefabric.parser import Parser
from parsefabric.patterns import RegexPattern
from parsefabric.summarization import EvidenceSummarizer

DATA = Path(__file__).resolve().parent / "data"
SAMPLES: dict[str, str] = {
    "Shop incident (mixed)": "mixed-shop-incident.txt",
    "Audit review (mixed)": "mixed-audit-review.txt",
    "Inventory (custom log format)": "mixed-custom-clock.txt",
    "Shop SQL statements": "shop-operations.sql",
    "Large incident log": "incident-mixed.log",
    "Timestamped operations": "timestamped-operations.log",
    "JSON incident record": "incident-record.json",
}
PARSERS = (
    "Mixed: built-ins + custom SQL",
    "Mixed: built-ins only",
    "Timestamped logs",
    "Application logs",
    "JSON",
    "Custom SQL",
)


@dataclass(frozen=True)
class PlaygroundOptions:
    parser_name: str
    log_format: str = "ISO timestamp"
    source_id: str = "pasted-input"
    llm_enabled: bool = False
    max_aggregates: int = 10


def sample_text(name: str) -> str:
    """Load only one of the checked-in demo inputs."""
    try:
        filename = SAMPLES[name]
    except KeyError as error:
        raise ValueError(f"unknown sample: {name}") from error
    return (DATA / filename).read_text(encoding="utf-8")


def build_parser(options: PlaygroundOptions) -> Parser:
    if options.log_format not in ("ISO timestamp", "Bracketed timestamp"):
        raise ValueError(f"unknown log format: {options.log_format}")
    bracketed = options.log_format == "Bracketed timestamp"
    if options.parser_name == "Mixed: built-ins + custom SQL":
        return make_parser(
            timestamped=True,
            custom_log_format=bracketed,
        )
    if options.parser_name == "Mixed: built-ins only":
        metrics = CLIOutputParser(
            [
                RegexPattern(
                    "measurement",
                    r"^METRIC (?P<name>[a-z_]+): (?P<value>\d+)$",
                    event_type="metric",
                )
            ],
            name="shop-metrics",
        )
        return MixedContentParser(
            routes=[
                (
                    RegexPattern(
                        "log-route",
                        r"^\[" if bracketed else r"^\d{4}-\d\d-\d\dT\S+\s+",
                    ),
                    TimestampedLogParser(
                        line_pattern=_BRACKETED_LOG if bracketed else None,
                    ),
                ),
                (
                    RegexPattern("json-route", r"^\{"),
                    JSONParser(),
                ),
                (RegexPattern("metric-route", r"^METRIC\b"), metrics),
            ],
        )
    if options.parser_name == "Timestamped logs":
        return TimestampedLogParser(
            line_pattern=_BRACKETED_LOG if bracketed else None,
        )
    if options.parser_name == "Application logs":
        return ApplicationLogParser()
    if options.parser_name == "JSON":
        return JSONParser()
    if options.parser_name == "Custom SQL":
        return SQLStatementParser()
    raise ValueError(f"unknown parser: {options.parser_name}")


async def run_parse(
    source: str, options: PlaygroundOptions, *, model: BaseLanguageModel | None = None
) -> tuple[ParseResult, tuple[EvidenceAggregate, ...]]:
    """Parse and aggregate the same complete input without mutating it."""
    if not isinstance(source, str):
        raise TypeError("input must be text")
    if not source.strip():
        raise ValueError("paste some input data before parsing")
    if not options.source_id.strip():
        raise ValueError("source ID must not be empty")
    summarizer = None
    if options.llm_enabled:
        if model is None:
            raise ConfigurationError(
                "LLM summarization requires a configured LangChain model. "
                "Set PARSEFABRIC_LLM_API_KEY and install the openai extra."
            )
        summarizer = EvidenceSummarizer(model, max_aggregates=options.max_aggregates)
    parser = build_parser(options)
    engine = ParseEngine()
    result = await engine.parse(
        parser, source, ParseContext(source_id=options.source_id)
    )
    warnings = list(result.warnings)
    if not result.events:
        warnings.append("The selected parser found no matching events.")
    if options.parser_name.startswith("Mixed:"):
        untyped_logs = sum(
            event.event_type == "log"
            and event.timestamp is None
            and event.evidence.parser_name == "mixed-content"
            for event in result.events
        )
        if untyped_logs:
            warnings.append(
                f"{untyped_logs} log lines were classified without timestamps "
                f"using the mixed fallback. Selected format: {options.log_format}."
            )
    result = replace(result, warnings=tuple(warnings))
    aggregates = await engine.aggregate(parser, result.events)
    if summarizer is not None:
        try:
            result = await summarizer.summarize_result(result, aggregates)
        except Exception as error:
            raise ParseError(f"LLM summarization failed: {error}") from error
    return result, aggregates


async def verify_lossless(
    source: str, options: PlaygroundOptions, aggregates: tuple[EvidenceAggregate, ...]
) -> int:
    """Rebuild every event from the aggregates and return how many were verified."""
    parser = build_parser(options)
    events = await ParseEngine().materialize(
        parser, source, aggregates, ParseContext(source_id=options.source_id)
    )
    return len(events)
