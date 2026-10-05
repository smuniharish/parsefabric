"""tree-sitter code detection, msgspec JSON, and jc command output."""

from __future__ import annotations

import pickle

import pytest

from parsefabric.builtins import (
    DEFAULT_CODE_LANGUAGES,
    CLIOutputParser,
    CodeDetector,
    JSONParser,
    MixedContentParser,
)
from parsefabric.engine import ParseEngine
from parsefabric.errors import ConfigurationError
from parsefabric.patterns import RegexPattern

PROSE = [
    "operator note: customer support notified",
    "request_id=req-4100 route=/v1/api/items",
    "done",
    "pass",
    "status: ok",
    "Host: example.com",
    "Total (approx)",
    "select the order from the menu",
    "METRIC reconciliation_candidates: 24",
    '{"service":"shop","state":"degraded"}',
    "Note: the database timed out.",
    "1. Restart the service",
]
CODE = [
    ("import os", "python"),
    ("def retry_api():\n    return client.get('/v1/api')", "python"),
    ("function f(a) {\n  return a + 1;\n}", "javascript"),
    ("package main", "go"),
    ('fn main() {\n    println!("hi");\n}', "rust"),
    ("#include <stdio.h>", "c"),
    ("UPDATE shop.orders SET status = 'processing' WHERE id = 4101;", "sql"),
    ("select id from t;", "sql"),
]


@pytest.mark.parametrize("text", PROSE)
def test_prose_is_not_code(text: str) -> None:
    assert CodeDetector().detect(text) is None


@pytest.mark.parametrize(("text", "language"), CODE)
def test_code_language_is_detected(text: str, language: str) -> None:
    assert CodeDetector().detect(text) == language


def test_detector_validates_languages_and_pickles() -> None:
    with pytest.raises(ValueError, match="prose"):
        CodeDetector(["bash"])
    with pytest.raises(ValueError, match="unknown"):
        CodeDetector(["no-such-language"])
    with pytest.raises(TypeError):
        CodeDetector("python")
    detector = pickle.loads(pickle.dumps(CodeDetector(["sql"])))
    assert detector.languages == ("sql",)
    assert detector.detect("import os") is None
    assert detector.detect("SELECT 1") == "sql"
    assert "python" in DEFAULT_CODE_LANGUAGES


def test_detector_cache_is_bounded_least_recently_used_and_thread_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from parsefabric.builtins import code_detection

    monkeypatch.setattr(code_detection, "_CACHE_SIZE", 2)
    detector = CodeDetector(["python"])
    calls: list[str] = []
    detect = detector._detect

    def counting(text: str) -> str | None:
        calls.append(text)
        return detect(text)

    monkeypatch.setattr(detector, "_detect", counting)
    assert detector.detect("import os") == "python"
    assert detector.detect("x = f()") == "python"
    assert detector.detect("import os") == "python"
    assert detector.detect("plain words") is None
    assert detector.detect("import os") == "python"
    assert detector.detect("x = f()") == "python"
    assert calls == ["import os", "x = f()", "plain words", "x = f()"]
    long_text = "import os\n" * 200
    assert detector.detect(long_text) == "python"
    assert detector.detect(long_text) == "python"
    assert calls.count(long_text) == 2
    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = [f"value_{index} = f()" for index in range(64)]
        assert set(pool.map(detector.detect, texts * 4)) == {"python"}
    assert len(detector._cache) <= 2


def test_detector_handles_deeply_nested_code_without_recursion_errors() -> None:
    detector = CodeDetector(["python", "sql"])
    assert detector.detect("x = " + "(" * 3000 + "f()" + ")" * 3000) == "python"
    assert detector.detect("SELECT " + "(" * 3000 + "1" + ")" * 3000 + ";") in {
        "sql",
        None,
    }


async def test_mixed_content_detects_code_blocks_by_language() -> None:
    source = (
        "operator note: retry scheduled\n"
        "@app.get('/')\n"
        "def index():\n"
        "    return 1\n"
        "\n"
        "SELECT id, total\n"
        "FROM shop.orders\n"
        "WHERE status = 'pending';\n"
        "```\n"
        "const x = require('fs');\n"
        "```\n"
        "done\n"
    )
    parser = MixedContentParser()
    result = await parser.parse(source)
    assert [
        (event.event_type, event.attributes.get("language")) for event in result.events
    ] == [
        ("other", None),
        ("code", "python"),
        ("code", "python"),
        ("code", "python"),
        ("other", None),
        ("code", "sql"),
        ("code", "sql"),
        ("code", "sql"),
        ("fence", "javascript"),
        ("code", "javascript"),
        ("fence", "javascript"),
        ("other", None),
    ]
    assert [event.evidence.line_number for event in result.events] == list(range(1, 13))
    engine = ParseEngine()
    aggregates = await engine.aggregate(parser, result.events)
    assert await engine.materialize(parser, source, aggregates) == result.events
    disabled = await MixedContentParser(code_languages=()).parse(source)
    assert {event.event_type for event in disabled.events[:8]} == {"other"}
    with pytest.raises(ValueError, match="reserved"):
        MixedContentParser([RegexPattern("code", r"x")])


async def test_json_parser_keeps_big_integers_and_rejects_non_standard_numbers() -> (
    None
):
    big = 2**100
    (event,) = (await JSONParser().parse(f'{{"id": {big}}}')).events
    assert event.attributes["value"] == {"id": big}
    assert type(event.attributes["value"]["id"]) is int  # type: ignore[index]
    for text in ('{"a": NaN}', "1e400", "[Infinity]"):
        result = await JSONParser().parse(text)
        assert result.events[0].event_type == "unparsed"
        assert result.errors[0].error_type in {"DecodeError", "ValidationError"}


async def test_cli_output_parser_uses_jc_command_parsers() -> None:
    source = (
        "Filesystem     1K-blocks     Used Available Use% Mounted on\n"
        "/dev/sda1       20509264 13424508   6015900  70% /\n"
        "tmpfs            1018508        0   1018508   0% /dev/shm\n"
    )
    parser = CLIOutputParser(command="df")
    engine = ParseEngine()
    result = await engine.parse(parser, source)
    assert [event.attributes["mounted_on"] for event in result.events] == [
        "/",
        "/dev/shm",
    ]
    assert result.events[0].attributes["use_percent"] == 70
    assert {event.evidence.pattern_name for event in result.events} == {"df"}
    assert not parser.capabilities.partitionable
    aggregates = await engine.aggregate(parser, result.events)
    assert await engine.materialize(parser, source, aggregates) == result.events
    (kv,) = (await CLIOutputParser(command="kv").parse("name=shop\nport=8080")).events
    assert kv.attributes == {"name": "shop", "port": "8080"}
    failed = await CLIOutputParser(command="ping").parse("garbage")
    assert failed.events[0].event_type == "unparsed"
    assert failed.errors
    empty = await CLIOutputParser(command="df").parse("garbage")
    assert (empty.events, empty.errors) == ((), ())
    assert empty.warnings == ("jc 'df' found no records in non-blank output",)
    assert (await CLIOutputParser(command="df").parse(" \n")).warnings == ()


def test_cli_output_parser_configuration_is_validated() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CLIOutputParser()
    with pytest.raises(ValueError, match="exactly one"):
        CLIOutputParser([], command="df")
    with pytest.raises(ValueError, match="unknown"):
        CLIOutputParser(command="no-such-command")
    with pytest.raises(ValueError, match="streaming"):
        CLIOutputParser(command="csv_s")
    with pytest.raises(ConfigurationError):
        CLIOutputParser(command="df").register_pattern(RegexPattern("x", r"x"))
