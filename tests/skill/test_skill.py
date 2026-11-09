"""The Agent Skills are valid, self-consistent, evaluated, and their scripts and templates pass."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from typing import TYPE_CHECKING

import pytest
from skills_ref import read_properties, validate

import parsefabric
from tests.support.paths import ROOT

if TYPE_CHECKING:
    from pathlib import Path

SKILLS_ROOT = ROOT / "parsefabric-skills" / "skills"
SKILLS = sorted(path for path in SKILLS_ROOT.iterdir() if (path / "SKILL.md").is_file())
CORE = SKILLS_ROOT / "parsefabric"
EXTEND = SKILLS_ROOT / "parsefabric-extend"
CHECK_EXTENSION = EXTEND / "scripts" / "check_extension.py"
LINK = re.compile(r"\]\(([^)#<>\s]+)(?:#[^)]*)?\)")
# Third-party langsmith still calls asyncio.iscoroutinefunction, which warns on Python 3.15.
STRICT_WARNINGS = ["-W", "error", "-W", "ignore:'asyncio.iscoroutinefunction':DeprecationWarning"]
by_name = pytest.mark.parametrize("skill", SKILLS, ids=lambda path: path.name)


def run(*arguments: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
        cwd=cwd,
    )


def pytest_run(target: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    # A private basetemp keeps the nested run away from the user-wide pytest temp directory.
    return run(
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={tmp_path}",
        f"--rootdir={target}",
        str(target),
        cwd=target,
    )


def check_extension(*arguments: str) -> subprocess.CompletedProcess[str]:
    return run(str(CHECK_EXTENSION), *arguments, "--json")


def test_both_skills_exist_and_skills_cli_discovers_them() -> None:
    assert [path.name for path in SKILLS] == ["parsefabric", "parsefabric-extend"]
    config = json.loads((ROOT / "skills.sh.json").read_text(encoding="utf-8"))
    assert [(ROOT / path).resolve() for path in config["paths"]] == [SKILLS_ROOT.resolve()]


@by_name
def test_the_skill_follows_the_agent_skills_specification(skill: Path) -> None:
    properties = read_properties(skill)

    assert validate(skill) == []
    assert properties.name == skill.name
    assert properties.license == "Apache-2.0"
    assert properties.metadata["version"] == parsefabric.__version__
    assert properties.description.startswith("Use this skill when")
    assert "Do not use it" in properties.description
    assert len((skill / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 500


@by_name
def test_references_are_one_level_deep_linked_and_every_link_resolves(skill: Path) -> None:
    body = (skill / "SKILL.md").read_text(encoding="utf-8")
    references = sorted((skill / "references").iterdir())
    assert all(path.is_file() and path.suffix == ".md" for path in references)
    for path in references:
        assert f"](references/{path.name})" in body, f"SKILL.md never links {path.name}"
    for page in skill.rglob("*.md"):
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if "://" not in target:
                assert (page.parent / target).is_file(), f"{page.name} links to {target}"


@by_name
def test_every_bundled_script_and_asset_is_mentioned_by_the_skill(skill: Path) -> None:
    body = (skill / "SKILL.md").read_text(encoding="utf-8")
    bundled = [
        path
        for folder in ("scripts", "assets")
        if (skill / folder).is_dir()
        for path in (skill / folder).glob("*.py")
    ]
    assert bundled
    for path in bundled:
        assert f"{path.parent.name}/{path.name}" in body, f"SKILL.md never mentions {path.name}"


@by_name
def test_the_evals_are_well_formed(skill: Path) -> None:
    evals = json.loads((skill / "evals" / "evals.json").read_text(encoding="utf-8"))

    assert evals["skill_name"] == skill.name
    cases = evals["evals"]
    assert len(cases) >= 3
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["prompt"].strip()
        assert case["expected_output"].strip()
        assert len(case["assertions"]) >= 3
        for file in case.get("files", []):
            assert (skill / "evals" / file).is_file(), file


@by_name
def test_the_trigger_queries_are_balanced_and_split(skill: Path) -> None:
    data = json.loads((skill / "evals" / "trigger_queries.json").read_text(encoding="utf-8"))
    queries = data["queries"]

    assert data["skill_name"] == skill.name
    assert len(queries) >= 16
    assert len({query["query"] for query in queries}) == len(queries)
    for split in ("train", "validation"):
        labels = [query["should_trigger"] for query in queries if query["split"] == split]
        assert True in labels, f"{split} has no query that should trigger"
        assert False in labels, f"{split} has no near-miss query"
    train = sum(query["split"] == "train" for query in queries)
    assert 0.5 <= train / len(queries) <= 0.7
    positives = sum(query["should_trigger"] for query in queries)
    assert 0.4 <= positives / len(queries) <= 0.6


def test_no_query_triggers_both_skills() -> None:
    def triggers(skill: Path) -> set[str]:
        data = json.loads((skill / "evals" / "trigger_queries.json").read_text(encoding="utf-8"))
        return {query["query"].lower() for query in data["queries"] if query["should_trigger"]}

    core, extend = triggers(CORE), triggers(EXTEND)
    assert not core & extend, "a query must not trigger both skills"


def test_the_setup_check_passes() -> None:
    completed = run(*STRICT_WARNINGS, str(CORE / "scripts" / "verify_setup.py"), "--langchain")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "FAIL" not in completed.stdout
    assert "LanguageModel contract" in completed.stdout
    assert completed.stdout.rstrip().endswith("All checks passed.")


def test_the_setup_check_reports_json() -> None:
    completed = run(*STRICT_WARNINGS, str(CORE / "scripts" / "verify_setup.py"), "--json")
    report = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stderr
    assert report["ok"] is True
    assert report["summary"] == "All checks passed."
    assert {check["status"] for check in report["checks"]} <= {"PASS", "INFO"}


def _release(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_the_setup_check_requires_the_package_dependency_ranges() -> None:
    source = (CORE / "scripts" / "verify_setup.py").read_text(encoding="utf-8")
    checked: dict[str, tuple[tuple[int, ...], tuple[int, ...] | None]] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.AnnAssign):
            continue
        target = node.target
        if isinstance(target, ast.Name) and target.id in {"REQUIRED", "LANGCHAIN"}:
            assert node.value is not None
            checked |= ast.literal_eval(node.value)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {}
    for requirement in [*project["dependencies"], *project["optional-dependencies"]["langchain"]]:
        match = re.fullmatch(r"([\w-]+)>=([\d.]+)(?:,<([\d.]+))?", requirement)
        assert match, requirement
        name, low, high = match.groups()
        declared[name] = (_release(low), _release(high) if high else None)

    assert checked == declared


def test_the_parsing_template_passes(tmp_path: Path) -> None:
    completed = pytest_run(CORE / "assets", tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "3 passed" in completed.stdout


def test_the_extension_templates_pass_their_tests(tmp_path: Path) -> None:
    completed = pytest_run(EXTEND / "assets", tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    # 3 parser tests and 2 sink tests.
    assert "5 passed" in completed.stdout


@pytest.mark.parametrize(
    ("factory", "extension", "arguments"),
    [
        ("parser_template:KeyValueParser", "Parser", ("--input", "{records}")),
        ("sink_template:BatchingSink", "ObservabilitySink", ()),
        ("patterns:DISK_FULL", "Pattern", ("--matching", "disk full", "--other", "disk ok")),
        ("parsefabric.aggregation:EvidenceAggregator", "Aggregator", ()),
        ("parsefabric.codecs:EvidenceCodec", "AggregateCodec", ()),
        ("parsefabric.codecs:StrictJSONCodec", "JSONCodec", ()),
        ("parsefabric.partitioning:LinePartitioner", "Partitioner", ()),
        ("parsefabric.execution:ThreadExecutionBackend", "ExecutionBackend", ()),
        ("parsefabric.registry:InMemoryParserRegistry", "ParserRegistry", ()),
        ("parsefabric.compression:ApproximateTokenizer", "Tokenizer", ()),
    ],
)
def test_the_extension_check_passes_conforming_extensions(
    factory: str, extension: str, arguments: tuple[str, ...], tmp_path: Path
) -> None:
    records = tmp_path / "records.kv"
    records.write_text("event=login level=info user=alice\nevent=export level=error\n")
    (tmp_path / "patterns.py").write_text(
        "from parsefabric.patterns import ExactPattern\n\n"
        'DISK_FULL = ExactPattern("disk_full", "disk full")\n',
        encoding="utf-8",
    )
    where = tmp_path if factory.startswith("patterns:") else EXTEND / "assets"
    resolved = [argument.format(records=records) for argument in arguments]
    completed = check_extension(factory, "--path", str(where), *resolved)
    report = json.loads(completed.stdout)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (report["ok"], report["extension"], report["error"]) == (True, extension, None)


def test_the_extension_check_names_a_broken_promise(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text(
        "from parsefabric.compression import Tokenizer\n\n\n"
        "class Shrinking(Tokenizer):\n"
        "    async def count(self, text):\n"
        "        return 5 - len(text) if text else 0\n",
        encoding="utf-8",
    )
    completed = check_extension("broken:Shrinking", "--path", str(tmp_path))
    report = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert report["check"] == "check_tokenizer"
    assert report["error"] == "counts must be integers that never shrink when text is appended"


def test_the_extension_check_requires_the_inputs_it_needs() -> None:
    completed = check_extension("parser_template:KeyValueParser", "--path", str(EXTEND / "assets"))
    report = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert report["error"] == "checking a Parser needs --input FILE"


@pytest.mark.parametrize("factory", ["no_such_module:Factory", "json:JSONDecoder"])
def test_the_extension_check_rejects_what_it_cannot_check(factory: str) -> None:
    completed = check_extension(factory)
    report = json.loads(completed.stdout)

    assert completed.returncode == 2
    assert report["error"].startswith(f"cannot load {factory}")
