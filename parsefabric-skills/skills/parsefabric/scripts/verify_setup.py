"""Check that ParseFabric is installed and works in this Python environment.

Runs offline and changes nothing. Prints one PASS, FAIL, or INFO line per check:

    python scripts/verify_setup.py              # core; LangChain too when installed
    python scripts/verify_setup.py --langchain  # require the LangChain extra
    python scripts/verify_setup.py --json       # one JSON object on stdout

Exit codes: 0 every check passed, 1 a check failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import sys
from importlib import metadata

REQUIRED: dict[str, tuple[tuple[int, ...], tuple[int, ...] | None]] = {
    "jc": ((1, 26, 2), (2,)),
    "opentelemetry-api": ((1, 45, 2), (2,)),
    "pydantic": ((2, 14, 3), (3,)),
    "structlog": ((26, 1, 0), None),
    "tree-sitter": ((0, 26, 0), (1,)),
    "tree-sitter-language-pack": ((1, 25, 0), (2,)),
    "typing-extensions": ((4, 16, 0), (5,)),
}
LANGCHAIN: dict[str, tuple[tuple[int, ...], tuple[int, ...] | None]] = {
    "langchain-core": ((1, 7, 6), (2,)),
}
OPTIONAL = ("langgraph", "opentelemetry-sdk")
LOG = (
    "2026-10-04T08:15:00Z INFO checkout started\n"
    "2026-10-04T08:15:02Z ERROR payment gateway timed out after 30s\n"
    "2026-10-04T08:15:03Z ERROR payment gateway timed out after 30s\n"
)

failures: list[str] = []
results: list[dict[str, str]] = []
as_json = False


def emit(status: str, message: str) -> None:
    results.append({"status": status, "message": message})
    if not as_json:
        print(f"{status}  {message}")


def report(passed: bool, message: str) -> bool:
    emit("PASS" if passed else "FAIL", message)
    if not passed:
        failures.append(message)
    return passed


def installed(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def release(version: str) -> tuple[int, ...]:
    """The numeric release of a version string: "1.2.12rc1" -> (1, 2, 12)."""
    numbers = []
    for part in version.split(".")[:3]:
        digits = re.match(r"\d+", part)
        numbers.append(int(digits.group()) if digits else 0)
    return tuple(numbers)


def dotted(version: tuple[int, ...]) -> str:
    return ".".join(map(str, version))


def check_environment(*, langchain: bool) -> bool:
    report(
        sys.version_info >= (3, 12),
        f"Python {platform.python_version()} (3.12 or newer required)",
    )
    version = installed("parsefabric")
    if version is None:
        return report(False, "parsefabric is not installed: pip install parsefabric")
    report(release(version)[:1] == (1,), f"parsefabric {version} (1.x expected by this skill)")
    required = REQUIRED | LANGCHAIN if langchain else REQUIRED
    for distribution, (lowest, below) in required.items():
        found = installed(distribution)
        compatible = (
            found is not None
            and lowest <= release(found)
            and (below is None or release(found) < below)
        )
        bounds = f">={dotted(lowest)}" + (f",<{dotted(below)}" if below else "")
        report(
            compatible,
            f"{distribution} {found or 'is not installed'} ({bounds} required)"
            + (
                '; install "parsefabric[langchain]"'
                if distribution in LANGCHAIN and not compatible
                else ""
            ),
        )
    extras = {name: installed(name) for name in OPTIONAL}
    present = [f"{name} {version}" for name, version in extras.items() if version]
    absent = [name for name, version in extras.items() if not version]
    emit(
        "INFO",
        f"optional integrations: {', '.join(present) or 'none'}"
        + (f" (not installed: {', '.join(absent)})" if absent else ""),
    )
    return not failures


async def check_parsing() -> None:
    from parsefabric import ParseContext, ParseEngine
    from parsefabric.builtins import ApplicationLogParser

    parser = ApplicationLogParser()
    engine = ParseEngine()
    context = ParseContext(source_id="verify.log")
    result = await engine.parse(parser, LOG, context)
    found = sorted({(event.event_type, event.evidence.line_number) for event in result.events})
    report(
        found == [("error", 2), ("error", 3), ("timeout", 2), ("timeout", 3)] and not result.errors,
        f"parsed {len(result.events)} events with line evidence: {found}",
    )
    aggregates = await engine.aggregate(parser, result.events)
    stored = await engine.serialize(aggregates)
    restored = await engine.deserialize(stored)
    events = await engine.materialize(parser, LOG, restored, context)
    report(
        restored == aggregates and events == result.events,
        f"lossless round trip through {len(stored)} stored characters",
    )


async def check_mixed_content() -> None:
    from parsefabric import ParseContext
    from parsefabric.builtins import MixedContentParser

    parser = MixedContentParser(code_detector=None)
    text = LOG + "prose that no parser claims\n"
    result = await parser.parse(text, ParseContext(source_id="mixed"))
    kinds = [event.event_type for event in result.events]
    report(
        kinds == ["log", "log", "log", "other"] and not result.errors,
        f"mixed content kept every line: {kinds}",
    )


async def check_langchain() -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from parsefabric.integrations.langchain import LangChainLanguageModel
    from parsefabric.testing import check_language_model

    model = LangChainLanguageModel(FakeListChatModel(responses=["OK"]))
    reply = await check_language_model(model)
    report(reply == "OK", f"{model.name} passes the LanguageModel contract")


def main() -> int:
    global as_json
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--langchain", action="store_true", help="Require the LangChain extra.")
    parser.add_argument("--json", action="store_true", help="Print one JSON object to stdout.")
    arguments = parser.parse_args()
    as_json = arguments.json
    langchain = arguments.langchain or installed("langchain-core") is not None
    if not langchain:
        emit("INFO", 'LangChain checks skipped; install "parsefabric[langchain]" to enable them.')
    if check_environment(langchain=langchain):
        checks = [check_parsing, check_mixed_content]
        if langchain:
            checks.append(check_langchain)
        for check in checks:
            try:
                asyncio.run(check())
            except Exception as error:  # report every failing check, then the summary
                report(False, f"{check.__name__}: {type(error).__name__}: {error}")
    summary = "All checks passed." if not failures else f"{len(failures)} check(s) failed."
    if as_json:
        print(json.dumps({"ok": not failures, "summary": summary, "checks": results}, indent=2))
    else:
        print(summary)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
