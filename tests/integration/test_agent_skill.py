"""The Agent Skill distribution follows the Agent Skills specification."""

import re

from tests.support.paths import ROOT

DISTRIBUTION = ROOT / "parsefabric-skills"
SKILL = DISTRIBUTION / "skills" / "parsefabric"
_FRONTMATTER = re.compile(r"\A---\n(?P<header>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _frontmatter() -> tuple[dict[str, str], str]:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    match = _FRONTMATTER.match(text)
    assert match, "SKILL.md must start with YAML frontmatter"
    fields = dict(
        line.split(": ", 1) for line in match["header"].splitlines() if line.strip()
    )
    return fields, match["body"]


def test_distribution_contains_exactly_one_skill() -> None:
    skills = sorted(path.name for path in (DISTRIBUTION / "skills").iterdir())

    assert skills == ["parsefabric"]
    assert (DISTRIBUTION / "README.md").is_file()
    assert (DISTRIBUTION / "validation" / "README.md").is_file()


def test_frontmatter_has_only_the_required_fields() -> None:
    fields, _ = _frontmatter()

    assert list(fields) == ["name", "description"]


def test_name_matches_the_directory_and_the_specification() -> None:
    name = _frontmatter()[0]["name"]

    assert name == SKILL.name
    assert 1 <= len(name) <= 64
    assert _NAME.fullmatch(name)


def test_description_says_what_the_skill_does_and_when_to_use_it() -> None:
    description = _frontmatter()[0]["description"]

    assert 1 <= len(description) <= 1024
    assert "parsefabric" in description
    assert "Use when" in description


def test_body_stays_within_the_recommended_size() -> None:
    body = _frontmatter()[1]

    assert len(body.splitlines()) < 500
    for section in (
        "## Activate when",
        "## Required workflow",
        "## Integration rules",
        "## Prohibited shortcuts",
        "## Verification checklist",
    ):
        assert section in body
