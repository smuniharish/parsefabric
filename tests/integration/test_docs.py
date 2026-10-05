"""The documentation stays runnable, linked and in sync with its sources."""

import contextlib
import hashlib
import io
import json
import re
import struct
from pathlib import Path

import pytest

from tests.support.markdown import Snippet, python_snippets
from tests.support.paths import DOCS, ROOT

DIAGRAMS = ROOT / "diagrams"
RENDERED = DOCS / "assets" / "diagrams"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RENDER_HINT = "diagram sources changed; run: node scripts/render_diagrams.mjs"
LINE_LIMIT = 88

MARKDOWN = sorted(
    {
        *DOCS.rglob("*.md"),
        *ROOT.glob("*.md"),
        *(ROOT / "parsefabric-skills").rglob("*.md"),
        ROOT / "examples" / "README.md",
        ROOT / "examples" / "integrations" / "README.md",
        ROOT / "benchmarks" / "README.md",
    }
)
SNIPPETS = [snippet for path in MARKDOWN for snippet in python_snippets(path)]

_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^)\s]+)")
_REPOSITORY = re.compile(
    r"^https://(?:github\.com/smuniharish/parsefabric/(?:blob|tree)/main"
    r"|raw\.githubusercontent\.com/smuniharish/parsefabric/main)/(?P<path>[^#?]+)"
)
_READ_THE_DOCS = re.compile(
    r"^https://parsefabric\.readthedocs\.io/en/latest/(?P<page>[^#?]*)"
)
_INTERNAL = re.compile(
    r"\bADRs?\b|architecture decision|[A-Za-z]:\\Users\\|/home/\w+/|\.ps1\b",
    re.IGNORECASE,
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _text_sha256(path: Path) -> str:
    """Hash text with LF line endings, matching scripts/render_diagrams.mjs."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    # Code spans and fences show syntax, not links.
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", "", text)
    return [match["target"].strip("<>") for match in _LINK.finditer(text)]


def _docs_page_exists(page: str) -> bool:
    page = page.strip("/")
    candidates = [DOCS / "index.md"] if not page else []
    candidates += [DOCS / f"{page}.md", DOCS / page / "index.md"]
    return any(candidate.is_file() for candidate in candidates)


@pytest.mark.parametrize(
    "snippet",
    SNIPPETS,
    ids=[f"{_relative(snippet.path)}:{snippet.line}" for snippet in SNIPPETS],
)
def test_python_snippet_runs_and_prints_the_documented_output(
    snippet: Snippet, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code = compile(snippet.code, f"{_relative(snippet.path)}:{snippet.line}", "exec")
    too_long = [line for line in snippet.code.splitlines() if len(line) > LINE_LIMIT]
    assert not too_long, f"lines longer than {LINE_LIMIT} characters: {too_long}"
    if not snippet.run:
        return
    monkeypatch.chdir(tmp_path)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exec(code, {"__name__": "__main__"})  # noqa: S102
    assert stdout.getvalue() == (snippet.expected_output or ""), (
        "printed output must match the documented output"
    )


def test_documentation_has_runnable_snippets() -> None:
    assert sum(snippet.run for snippet in SNIPPETS) >= 15


@pytest.mark.parametrize("path", MARKDOWN, ids=_relative)
def test_links_resolve_to_existing_files_and_pages(path: Path) -> None:
    broken = []
    for target in _links(path):
        if repository := _REPOSITORY.match(target):
            exists = (ROOT / repository["path"]).exists()
        elif read_the_docs := _READ_THE_DOCS.match(target):
            exists = _docs_page_exists(read_the_docs["page"])
        elif re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        else:
            exists = (path.parent / target.split("#")[0]).resolve().exists()
        if not exists:
            broken.append(target)

    assert not broken


@pytest.mark.parametrize("path", MARKDOWN, ids=_relative)
def test_documents_contain_no_internal_references(path: Path) -> None:
    assert not _INTERNAL.findall(path.read_text(encoding="utf-8"))


def test_manifest_matches_sources_and_config() -> None:
    manifest = json.loads((RENDERED / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["renderer"].startswith("@mermaid-js/mermaid-cli@")
    assert manifest["config"] == _text_sha256(DIAGRAMS / "mermaid-config.json"), (
        RENDER_HINT
    )
    assert manifest["sources"] == {
        path.name: _text_sha256(path) for path in sorted(DIAGRAMS.glob("*.mmd"))
    }, RENDER_HINT


def test_every_source_has_exactly_one_rendered_png() -> None:
    sources = {path.stem for path in DIAGRAMS.glob("*.mmd")}

    assert sources
    assert {path.stem for path in RENDERED.glob("*.png")} == sources


@pytest.mark.parametrize(
    "path", sorted(RENDERED.glob("*.png")), ids=lambda path: path.name
)
def test_rendered_diagram_is_a_legible_png(path: Path) -> None:
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])

    assert data[:8] == PNG_SIGNATURE
    assert data[12:16] == b"IHDR"
    assert 800 <= width <= 4000
    assert 400 <= height <= 4000


def test_every_diagram_is_shown_in_the_documentation() -> None:
    pages = "\n".join(path.read_text(encoding="utf-8") for path in DOCS.rglob("*.md"))

    assert {
        path.name for path in RENDERED.glob("*.png") if path.name not in pages
    } == set()
