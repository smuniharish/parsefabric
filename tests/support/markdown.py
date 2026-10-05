"""Extract Python snippets and their documented output from Markdown files."""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

SKIP_MARKER = "<!-- docs-test: skip -->"
"""Placed on the line before a fence: compile the snippet but do not run it."""

_FENCE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[ \t]*(?P<info>[^\n]*)\n"
    r"(?P<body>.*?)"
    r"^(?P=indent)(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Snippet:
    """One Python fence: its code, location and the output documented after it."""

    path: Path
    line: int
    code: str
    expected_output: str | None
    run: bool


def _language(info: str) -> str:
    words = info.split()
    return words[0] if words else ""


def python_snippets(path: Path) -> list[Snippet]:
    """Return every Python fence of ``path`` except embedded files.

    A ``text`` or ``json`` fence that directly follows a Python fence,
    separated at most by an ``Output:`` line, is that snippet's expected
    standard output.
    """
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    blocks = list(_FENCE.finditer(text))
    snippets: list[Snippet] = []
    for index, block in enumerate(blocks):
        if _language(block["info"]) != "python":
            continue
        code = textwrap.dedent(block["body"])
        if code.lstrip().startswith("--8<--"):
            continue
        preceding = text[: block.start()].rstrip().splitlines()
        expected = None
        if index + 1 < len(blocks):
            following = blocks[index + 1]
            between = text[block.end() : following.start()].strip()
            if between in {"", "Output:"} and _language(following["info"]) in {
                "text",
                "json",
            }:
                expected = textwrap.dedent(following["body"])
        snippets.append(
            Snippet(
                path=path,
                line=text.count("\n", 0, block.start()) + 1,
                code=code,
                expected_output=expected,
                run=not (preceding and preceding[-1].strip() == SKIP_MARKER),
            )
        )
    return snippets
