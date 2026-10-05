"""Local, interactive playground for ParseFabric's parsers.

Paste or pick a sample, choose a parser and inspect events, evidence and
aggregates. Requires streamlit and sqlglot (``uv sync`` in a checkout). Optional
LLM summaries use the PARSEFABRIC_LLM_* variables described in
``llm_summary_openai_compatible.py``.

Run: streamlit run examples/streamlit_app.py --server.address 127.0.0.1
"""

from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext

import streamlit as st
from langchain_core.language_models import BaseChatModel
from llm_summary_openai_compatible import open_model
from ui_backend import (
    PARSERS,
    SAMPLES,
    PlaygroundOptions,
    build_parser,
    run_parse,
    sample_text,
)

from parsefabric.aggregation import EvidenceAggregate
from parsefabric.compression import measure_compression
from parsefabric.errors import ParseError
from parsefabric.models import ParseResult


async def _parse(
    source: str, options: PlaygroundOptions
) -> tuple[ParseResult, tuple[EvidenceAggregate, ...]]:
    configured = (
        open_model() if options.llm_enabled else nullcontext[BaseChatModel | None](None)
    )
    async with configured as model:
        return await run_parse(source, options, model=model)


def show_json_output(label: str, text: str) -> None:
    if len(text) > 100_000:
        st.caption("Complete output below; highlighting is disabled for large results.")
        st.text_area(label, value=text, height=400, disabled=True)
    else:
        st.code(text, language="json", line_numbers=True, wrap_lines=True)


def main() -> None:
    st.set_page_config(page_title="ParseFabric playground", layout="wide")
    st.title("ParseFabric playground")
    st.caption(
        "Paste input or load a fictional sample, configure a parser, and run "
        "async parsing and lossless, source-referenced aggregation locally."
    )

    sample = st.sidebar.selectbox("Example input", tuple(SAMPLES))
    if "input_text" not in st.session_state:
        st.session_state["input_text"] = sample_text(sample)
    if "source_id" not in st.session_state:
        st.session_state["source_id"] = SAMPLES[sample]
    if st.sidebar.button("Load selected sample"):
        st.session_state["input_text"] = sample_text(sample)
        st.session_state["source_id"] = SAMPLES[sample]
    parser_name = st.sidebar.selectbox("Parser", PARSERS)
    if parser_name.startswith(("Mixed:", "Timestamped logs")):
        log_format = st.sidebar.selectbox(
            "Timestamped log format", ("ISO timestamp", "Bracketed timestamp")
        )
    else:
        log_format = "ISO timestamp"
    source_id = st.sidebar.text_input("Source ID", key="source_id")
    llm_enabled = st.sidebar.toggle("LLM summarization", value=False)
    max_aggregates = 10
    if llm_enabled:
        max_aggregates = int(
            st.sidebar.number_input(
                "Max aggregates per LLM call", min_value=2, value=10
            )
        )
        st.sidebar.caption(
            "Uses the server's PARSEFABRIC_LLM_API_KEY, PARSEFABRIC_LLM_BASE_URL "
            "and PARSEFABRIC_LLM_MODEL. Only aggregates are sent to the model."
        )
    st.sidebar.caption(
        "Mixed routing frames multiline JSON; ```sql fences are parsed as "
        "SQL (multi-line allowed) and other fences stay code; outside fences, "
        "each SQL statement must fit on one line. "
        "Aggregates group evidence by level/severity and reference 1-based "
        "input line positions; materialize() rebuilds every event from the input."
    )

    st.subheader("Input data with line numbers")
    input_lines = st.session_state["input_text"].splitlines()
    st.code(
        "\n".join(input_lines),
        language="text",
        line_numbers=True,
    )
    st.text_area("Edit input data", key="input_text", height=320)
    if st.button("Parse and aggregate", type="primary"):
        options = PlaygroundOptions(
            parser_name=parser_name,
            log_format=log_format,
            source_id=source_id,
            llm_enabled=llm_enabled,
            max_aggregates=max_aggregates,
        )
        try:
            result, aggregates = asyncio.run(
                _parse(st.session_state["input_text"], options)
            )
        except (ParseError, TypeError, ValueError, ImportError) as error:
            st.session_state.pop("latest", None)
            st.exception(error)
        else:
            st.session_state["latest"] = (
                result,
                aggregates,
                options,
                st.session_state["input_text"],
            )

    if "latest" not in st.session_state:
        st.info("Select a parser, then press Parse and aggregate.")
        return

    result, aggregates, used_options, parsed_source = st.session_state["latest"]
    st.subheader("Last run")
    st.caption(f"{used_options.parser_name} | source: {used_options.source_id}")
    events = [event.to_dict() for event in result.events]
    summaries = [aggregate.to_dict() for aggregate in aggregates]
    count_events, count_aggregates, count_errors = st.columns(3)
    count_events.metric("Events", len(events))
    count_aggregates.metric("Aggregates", len(summaries))
    count_errors.metric("Parse errors", len(result.errors))
    for warning in result.warnings:
        st.warning(warning)
    for error in result.errors:
        st.error(str(error))
    parser = build_parser(used_options)
    metrics = measure_compression(parsed_source, parser.serialize(aggregates))
    before, after, change, tokens = st.columns(4)
    before.metric("Input size (UTF-8)", f"{metrics.input_bytes:,} B")
    after.metric("Aggregate size (compact JSON)", f"{metrics.output_bytes:,} B")
    change.metric(
        "Byte reduction",
        (
            f"{metrics.reduction_percent:+.1f}%"
            if metrics.reduction_percent is not None
            else "N/A"
        ),
        delta=f"{metrics.bytes_saved:+,} B",
    )
    tokens.metric(
        "Token reduction (est.)",
        (
            f"{metrics.token_reduction_percent:+.1f}%"
            if metrics.token_reduction_percent is not None
            else "N/A"
        ),
        delta=f"{metrics.tokens_saved:+,} tokens",
    )
    evidence = [
        (aggregate, group, entry)
        for aggregate in aggregates
        for group in aggregate.groups
        for entry in group.evidence
    ]

    st.subheader("Grouped evidence")
    st.dataframe(
        [
            {
                "event_type": aggregate.event_type,
                "parser": aggregate.parser_name,
                "severity": group.severity,
                "message": (
                    json.dumps(entry.message, ensure_ascii=False)
                    if not isinstance(entry.message, str)
                    else entry.message
                ),
                "occurrences": entry.occurrences,
                "positions": ", ".join(
                    "?" if line is None else str(line) for line in entry.positions
                ),
            }
            for aggregate, group, entry in evidence
        ],
        hide_index=True,
    )
    st.subheader("Final aggregated output")
    st.caption(
        "The canonical parsefabric.aggregates/1 document from "
        "parser.serialize(), shown indented; sizes are measured on its compact "
        "form. Each evidence entry has a message, occurrences, and the 1-based "
        "line positions of its events in the input. The SHA-256 checksum covers "
        "every complete event."
    )
    show_json_output("Complete aggregates JSON", parser.serialize(aggregates, indent=2))
    st.subheader("Parsed events and evidence")
    st.caption("All events with complete evidence, timestamps, and attributes.")
    show_json_output(
        "Complete events JSON", json.dumps(events, indent=2, ensure_ascii=False)
    )
    st.subheader("Final ParseResult")
    if result.llm_result is not None:
        st.subheader("LLM summarization")
        st.text(result.llm_result)
    show_json_output(
        "Complete ParseResult JSON",
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
    )
    st.download_button(
        "Download complete JSON result",
        json.dumps(
            {
                "parser": used_options.parser_name,
                **result.to_dict(),
                "aggregates": summaries,
            },
            indent=2,
            ensure_ascii=False,
        ),
        file_name="parsefabric-result.json",
        mime="application/json",
    )


if __name__ == "__main__":
    main()
