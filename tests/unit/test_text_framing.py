"""Lazy framing matches Python line boundaries and exact UTF-8 byte widths."""

from dataclasses import replace
from itertools import product

import pytest

from parsefabric import ParseContext
from parsefabric.builtins import ApplicationLogParser
from parsefabric.parser import DeterministicParser
from parsefabric.parser._text import iter_text_lines
from parsefabric.partitioning import LinePartitioner
from parsefabric.patterns import RegexPattern

SEPARATORS = (
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
SEPARATOR_CHARACTERS = "".join(SEPARATORS)


@pytest.mark.parametrize(("first", "second"), tuple(product(SEPARATORS, repeat=2)))
def test_every_pair_of_line_boundaries_preserves_content_and_utf8_width(
    first: str, second: str
) -> None:
    for source in (
        f"é日本{first}timeout{second}\U0001f680",
        f"{first}{second}",
        f"é{first}{second}",
    ):
        expected = [
            (line.rstrip(SEPARATOR_CHARACTERS), len(line.encode("utf-8")))
            for line in source.splitlines(keepends=True)
        ]
        assert list(iter_text_lines(source)) == expected
        assert sum(width for _, width in expected) == len(source.encode("utf-8"))


@pytest.mark.parametrize("source", ["", "plain", "\n", "x\n", "\r\n", "x\r\n"])
def test_framing_does_not_add_a_phantom_trailing_line(source: str) -> None:
    assert len(list(iter_text_lines(source))) == len(source.splitlines())


def test_framing_is_lazy_and_does_not_preencode_the_remaining_source() -> None:
    lines = iter_text_lines("first\n\ud800")
    assert next(lines) == ("first", 6)
    with pytest.raises(UnicodeEncodeError):
        next(lines)


@pytest.mark.parametrize("separator", SEPARATORS)
def test_partitioning_normalizes_one_terminal_boundary_to_lf(separator: str) -> None:
    partitions = tuple(
        LinePartitioner(max_lines=1).partition(
            [f"é{separator}", f"日本{separator}"],
            capabilities=ApplicationLogParser().capabilities,
        )
    )
    assert [partition.content for partition in partitions] == ["é\n", "日本"]
    assert partitions[1].start_line == 2
    assert partitions[1].start_offset == len("é\n".encode())


@pytest.mark.parametrize("separator", SEPARATORS)
def test_partitioning_rejects_embedded_boundaries_that_corrupt_line_numbers(
    separator: str,
) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        tuple(
            LinePartitioner(max_lines=1).partition(
                [f"timeout{separator}timeout", "retry"],
                capabilities=ApplicationLogParser().capabilities,
            )
        )


@pytest.mark.parametrize("option", ["max_lines", "max_bytes"])
@pytest.mark.parametrize("value", [True, False, 1.5, 0, -1])
def test_partition_limits_are_positive_integers(option: str, value: object) -> None:
    with pytest.raises(ValueError, match=f"{option} must be a positive integer"):
        LinePartitioner(**{option: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("max_lines", [1, 2, 3])
@pytest.mark.parametrize("max_bytes", [16, 1024])
@pytest.mark.parametrize(
    "records",
    [
        ["", "timeout", "", "retry", ""],
        ["", "timeout é", "", "retry 日本", ""],
    ],
)
async def test_partition_boundaries_preserve_blank_lines_and_complete_byte_spans(
    max_lines: int,
    max_bytes: int,
    records: list[str],
) -> None:
    source = "\n".join(records)
    parser = DeterministicParser(
        [RegexPattern("record", r"^(?P<message>.*)$")], name="every-line"
    )
    expected = await parser.parse(source, ParseContext(source_id="s"))
    observed = []
    partitions = tuple(
        LinePartitioner(max_lines=max_lines, max_bytes=max_bytes).partition(
            records, source_id="s", capabilities=parser.capabilities
        )
    )
    assert "".join(partition.content for partition in partitions) == source
    for partition in partitions:
        assert len(partition.content.encode("utf-8")) <= max_bytes
        result = await parser.parse(
            partition.content,
            ParseContext(source_id="s", source_offset=partition.start_offset),
        )
        for event in result.events:
            assert event.evidence.line_number is not None
            observed.append(
                event.with_evidence(
                    replace(
                        event.evidence,
                        line_number=partition.start_line
                        + event.evidence.line_number
                        - 1,
                    )
                )
            )
    assert tuple(observed) == expected.events
