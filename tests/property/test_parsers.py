"""Properties of text framing and the built-in parsers."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from parsefabric.builtins import (
    ApplicationLogParser,
    CLIOutputParser,
    CodeDetector,
    JSONParser,
    MixedContentParser,
    TimestampedLogParser,
)
from parsefabric.builtins.application_log import default_patterns
from parsefabric.errors import ParseError
from parsefabric.models import ParseContext, ParseResult
from parsefabric.parser._text import iter_text_lines
from parsefabric.patterns import RegexPattern
from tests.support.strategies import (
    AWARE_DATETIMES,
    LINE_BREAKS,
    LINE_TEXT,
    UNICODE,
)

WHITESPACE = st.sampled_from([" ", "\t", "\u00a0", "\u3000", "\x1f"])
WORDS = st.sampled_from(
    [
        "timeout",
        "timed out",
        "retry",
        "attempt 3",
        "ERROR",
        "WARN",
        "warning",
        "OOM",
        "connection refused",
        "permission denied",
        "service down",
        "login failed",
        "db",
        "x",
        ":",
        "",
    ]
)
LOGISH_LINES = st.lists(st.one_of(WORDS, WHITESPACE), max_size=12).map("".join)


def _parse(parser: object, source: object, context: ParseContext | None = None):
    return asyncio.run(parser.parse(source, context))  # type: ignore[attr-defined]


def _reference_lines(text: str) -> list[tuple[str, int]]:
    lines = text.splitlines(keepends=True)
    return [
        (line.splitlines()[0] if line.splitlines() else "", len(line.encode("utf-8")))
        for line in lines
    ]


@given(st.text(UNICODE, max_size=200))
def test_framing_matches_splitlines_and_counts_every_byte(text: str) -> None:
    lines = list(iter_text_lines(text))
    assert lines == _reference_lines(text)
    assert sum(width for _, width in lines) == len(text.encode("utf-8"))


@given(st.lists(LINE_TEXT, max_size=10), st.lists(st.sampled_from(LINE_BREAKS)))
def test_ascii_fast_path_matches_the_general_path(
    records: list[str], breaks: list[str]
) -> None:
    separators = breaks or ["\n"]
    text = "".join(
        record + separators[index % len(separators)]
        for index, record in enumerate(records)
    )
    expected = _reference_lines(text)
    assert list(iter_text_lines(text)) == expected


_OLD_SIGNAL = re.compile(
    r"^(?=.*\b(?:timeout|timed out)\b)(?P<message>.*?)\s*$", re.IGNORECASE
)
_OLD_LEVEL = re.compile(
    r"^\s*(?:\d{4}-\d\d-\d\d[ T]\S+\s+)?"
    r"(?P<level>TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b"
    r"[:\s]*(?P<message>.*?)\s*$",
    re.IGNORECASE,
)


@given(LOGISH_LINES)
def test_linear_signal_pattern_matches_the_previous_expression(line: str) -> None:
    (timeout,) = [
        pattern for pattern in default_patterns() if pattern.name == "timeout"
    ]
    old = _OLD_SIGNAL.search(line)
    new = timeout.match(line)
    assert (old is None) == (new is None)
    if old is not None and new is not None:
        assert new.attributes["message"] == old.group("message")
        assert old.group("message") == line.rstrip()


@given(LOGISH_LINES)
def test_linear_log_level_pattern_matches_the_previous_expression(line: str) -> None:
    parser = MixedContentParser(code_languages=())
    (level,) = parser._patterns
    old = _OLD_LEVEL.search(line)
    new = level.match(line)
    assert (old is None) == (new is None)
    if old is not None and new is not None:
        expected = {key: value for key, value in old.groupdict().items() if value}
        assert new.attributes == expected | {"message": old.group("message")}


@given(st.lists(LOGISH_LINES, max_size=12), st.sampled_from(LINE_BREAKS), st.data())
def test_line_parsers_record_exact_spans_for_any_line_ending(
    lines: list[str], newline: str, data: st.DataObject
) -> None:
    text = newline.join(lines)
    offset = data.draw(st.integers(min_value=0, max_value=10_000))
    parser = ApplicationLogParser()
    result = _parse(parser, text, ParseContext(source_id="s", source_offset=offset))
    assert result == _parse(
        parser, text.encode("utf-8"), ParseContext("s", None, None, offset)
    )
    encoded = text.encode("utf-8")
    framed = list(iter_text_lines(text))
    starts = [offset]
    for _, width in framed:
        starts.append(starts[-1] + width)
    for event in result.events:
        evidence = event.evidence
        assert evidence.line_number is not None
        index = evidence.line_number - 1
        assert (evidence.start_offset, evidence.end_offset) == (
            starts[index],
            starts[index + 1],
        )
        raw = encoded[starts[index] - offset : starts[index + 1] - offset].decode()
        assert raw.startswith(framed[index][0])
    statistics = {item.pattern_name: item.matches for item in result.pattern_statistics}
    assert sum(statistics.values()) == len(result.events)


def _covered_lines(text: str, result: ParseResult) -> set[int]:
    starts: list[int] = []
    offset = 0
    for _, width in iter_text_lines(text):
        starts.append(offset)
        offset += width
    covered: set[int] = set()
    for event in result.events:
        evidence = event.evidence
        assert evidence.line_number is not None
        covered.add(evidence.line_number)
        assert evidence.start_offset is not None
        assert evidence.end_offset is not None
        covered.update(
            number
            for number, start in enumerate(starts, start=1)
            if evidence.start_offset <= start < evidence.end_offset
        )
    return covered


MIXED_LINES = st.sampled_from(
    [
        "ERROR database timeout",
        "WARN slow disk",
        '{"status": "ok"}',
        "{",
        '  "nested": [1, 2]',
        "}",
        "```sql",
        "```",
        "~~~",
        "SELECT 1;",
        "plain note",
        "",
        "  indented text",
    ]
)


@settings(max_examples=150)
@given(st.lists(MIXED_LINES, max_size=14), st.sampled_from(["\n", "\r\n", "\u2028"]))
def test_mixed_content_loses_no_line_and_rebuilds_its_events(
    lines: list[str], newline: str
) -> None:
    text = newline.join(lines)
    logs = ApplicationLogParser()
    parser = MixedContentParser(
        routes=[
            (RegexPattern("json-line", r"^\{"), JSONParser()),
            (RegexPattern("log-line", r"^(ERROR|WARN)\b"), logs),
        ],
        fence_routes={"sql": logs},
        code_languages=(),
    )
    result = _parse(parser, text, ParseContext(source_id="mixed"))
    framed = list(iter_text_lines(text))
    assert _covered_lines(text, result) == set(range(1, len(framed) + 1))
    numbers = [event.evidence.line_number or 0 for event in result.events]
    assert numbers == sorted(numbers)
    assert result == _parse(parser, text, ParseContext(source_id="mixed"))
    aggregates = asyncio.run(parser.aggregate(result.events))
    restored = asyncio.run(parser.aggregator.materialize(aggregates, result.events))
    assert restored == result.events


@settings(max_examples=60)
@given(st.text(UNICODE, max_size=120))
def test_code_detector_never_fails_on_arbitrary_text(text: str) -> None:
    detector = CodeDetector()
    language = detector.detect(text)
    assert language is None or language in detector.languages
    assert detector.detect(text) == language


@given(
    st.lists(
        st.tuples(
            AWARE_DATETIMES,
            st.sampled_from(["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]),
            LINE_TEXT.map(str.strip).filter(bool),
        ),
        min_size=1,
        max_size=10,
    ),
    st.sampled_from(["\n", "\r\n"]),
)
def test_timestamped_logs_preserve_every_line_exactly(
    rows: list[tuple[datetime, str, str]], newline: str
) -> None:
    text = newline.join(
        f"{moment.isoformat()} {level} {message}" for moment, level, message in rows
    )
    result = _parse(TimestampedLogParser(), text)
    assert [
        (event.timestamp, event.severity, event.attributes["message"])
        for event in result.events
    ] == rows
    assert [event.evidence.line_number for event in result.events] == list(
        range(1, len(rows) + 1)
    )


@given(LINE_TEXT.filter(lambda line: not re.match(r"^\S+\s+[A-Z]+\s+\S", line)))
def test_timestamped_logs_reject_lines_without_the_record_shape(line: str) -> None:
    with pytest.raises(ParseError):
        _parse(TimestampedLogParser(), line or "x")


@settings(max_examples=100)
@given(st.text(UNICODE, max_size=200))
def test_cli_parsers_never_fail_on_arbitrary_text(text: str) -> None:
    result = _parse(CLIOutputParser(command="kv"), text)
    if result.errors:
        assert [event.event_type for event in result.events] == ["unparsed"]
    else:
        assert all(event.event_type == "cli_record" for event in result.events)
        assert bool(result.warnings) == (not result.events and bool(text.strip()))
