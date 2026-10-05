"""Hypothesis strategies for ParseFabric values."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from hypothesis import strategies as st

from parsefabric.models import Evidence, JSONValue, ParsedEvent

LINE_BREAKS = (
    "\n",
    "\r",
    "\r\n",
    "\v",
    "\f",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x85",
    "\u2028",
    "\u2029",
)
UNICODE = st.characters(exclude_categories=("Cs",))
TEXT = st.text(UNICODE, max_size=24)
LINE_TEXT = st.text(
    st.characters(exclude_categories=("Cs",), exclude_characters="".join(LINE_BREAKS)),
    max_size=32,
)
NAMES = st.text(st.characters(exclude_categories=("Cs",)), min_size=1, max_size=10)
IDENTIFIERS = st.none() | NAMES
JSON_SCALARS = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**80), max_value=2**80)
    | st.floats(allow_nan=False, allow_infinity=False)
    | TEXT
)
JSON_VALUES: st.SearchStrategy[JSONValue] = st.recursive(
    JSON_SCALARS,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(TEXT, children, max_size=4)
    ),
    max_leaves=16,
)
ATTRIBUTES = st.dictionaries(TEXT, JSON_VALUES, max_size=4)
TIMEZONES = st.sampled_from(
    [
        UTC,
        timezone(timedelta(hours=5, minutes=30)),
        timezone(timedelta(hours=-8)),
    ]
)
# Hypothesis takes naive bounds and attaches the drawn time zone.
AWARE_DATETIMES = st.datetimes(
    min_value=datetime(1900, 1, 1),  # noqa: DTZ001
    max_value=datetime(2100, 1, 1),  # noqa: DTZ001
    timezones=TIMEZONES,
)


@st.composite
def evidence(draw: st.DrawFn) -> Evidence:
    """Draw valid evidence with a consistent byte span."""
    start = draw(st.none() | st.integers(min_value=0, max_value=10_000))
    end = (
        None
        if start is None
        else draw(st.none() | st.integers(min_value=start, max_value=start + 500))
    )
    return Evidence(
        source_id=draw(IDENTIFIERS),
        start_offset=start,
        end_offset=end,
        line_number=draw(st.none() | st.integers(min_value=1, max_value=10_000)),
        parser_name=draw(IDENTIFIERS),
        parser_version=draw(IDENTIFIERS),
        pattern_name=draw(IDENTIFIERS),
        partition_id=draw(IDENTIFIERS),
        correlation_id=draw(IDENTIFIERS),
    )


@st.composite
def events(draw: st.DrawFn) -> ParsedEvent:
    """Draw any valid event."""
    return ParsedEvent(
        event_type=draw(NAMES),
        attributes=draw(ATTRIBUTES),
        timestamp=draw(st.none() | AWARE_DATETIMES),
        severity=draw(st.none() | TEXT),
        confidence=draw(st.none() | st.floats(min_value=0, max_value=1)),
        evidence=draw(evidence()),
    )


@st.composite
def document_events(draw: st.DrawFn, *, max_size: int = 30) -> list[ParsedEvent]:
    """Draw the events of one source document, in source order.

    Events share a source and use a small vocabulary so that runs, repeated
    messages and interleaved findings occur often.
    """
    source_id = draw(IDENTIFIERS)
    parsers = draw(
        st.lists(
            st.tuples(NAMES, st.sampled_from(["1", "2"])),
            min_size=1,
            max_size=3,
            unique_by=lambda item: item[0],
        )
    )
    count = draw(st.integers(min_value=0, max_value=max_size))
    line = 1
    offset = 0
    result: list[ParsedEvent] = []
    for _ in range(count):
        line += draw(st.integers(min_value=0, max_value=2))
        width = draw(st.integers(min_value=0, max_value=6))
        gap = draw(st.integers(min_value=0, max_value=2))
        name, version = draw(st.sampled_from(parsers))
        located = draw(st.booleans())
        result.append(
            ParsedEvent(
                event_type=draw(st.sampled_from(["error", "warning", "record"])),
                attributes=draw(
                    st.sampled_from(
                        [
                            {"message": "timeout"},
                            {"message": "retry"},
                            {"value": [1, {"a": None}]},
                            {},
                        ]
                    )
                ),
                timestamp=draw(st.none() | AWARE_DATETIMES),
                severity=draw(st.sampled_from([None, "ERROR", "WARN"])),
                evidence=Evidence(
                    source_id=source_id,
                    start_offset=offset + gap if located else None,
                    end_offset=offset + gap + width if located else None,
                    line_number=line if located or draw(st.booleans()) else None,
                    parser_name=name,
                    parser_version=version,
                    pattern_name=draw(st.sampled_from([None, "p1", "p2"])),
                ),
            )
        )
        offset += gap + width
    return result
