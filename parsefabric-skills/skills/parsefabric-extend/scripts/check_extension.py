"""Check a ParseFabric extension against its contract, without pytest.

Imports a factory, works out which abstract base class the object it returns
subclasses, and runs the matching `parsefabric.testing` check:

    python scripts/check_extension.py myapp.parsing:OrderLogParser --input sample.log
    python scripts/check_extension.py myapp.parsing:ORDER --matching "order 7 failed" --other "ok"
    python scripts/check_extension.py myapp.detect:make_detector --expect "SELECT 1;=sql"
    python scripts/check_extension.py myapp.telemetry:KafkaSink --json

The factory is a class or a callable, sync or async, that takes no arguments
and returns a new extension, or an extension instance such as a module-level
pattern. Run it from the project root, or pass --path.

Inputs per extension point:

    Parser                  --input FILE (required): a representative source
    Pattern                 --matching TEXT and --other TEXT (both required)
    CodeDetector            --expect TEXT=LANGUAGE, repeatable; LANGUAGE "none" for prose
    CommandOutputBackend    --command NAME and --input FILE with its output
    Aggregator, AggregateCodec, Partitioner
                            --input FILE (optional): a log; a built-in sample otherwise.
                            Codecs receive EvidenceAggregator aggregates of the log.
    the others              nothing

Language models are called once, so a live model needs its credentials.

Exit codes: 0 the contract holds, 1 the contract is broken, 2 the factory
cannot be imported, is not an extension, or a required input is missing.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import traceback
from importlib import import_module
from pathlib import Path
from typing import Any

SAMPLE_LOG = (
    "2026-10-04T08:15:00Z INFO checkout started\n"
    "2026-10-04T08:15:02Z ERROR payment gateway timed out after 30s\n"
    "2026-10-04T08:15:03Z ERROR payment gateway timed out after 30s\n"
    "2026-10-04T08:15:04Z WARN retry scheduled\n"
)


class UsageError(Exception):
    """The extension cannot be checked with the given arguments."""


def load_factory(spec: str) -> Any:
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"expected MODULE:FACTORY, got {spec!r}")
    target: Any = import_module(module_name)
    for part in attribute.split("."):
        target = getattr(target, part)
    return target


async def build(factory: Any) -> Any:
    if any(isinstance(factory, base) for base, _ in contract_checks()):
        return factory
    if not callable(factory):
        raise TypeError(f"{factory!r} is not callable")
    value = factory()
    return await value if inspect.isawaitable(value) else value


def contract_checks() -> list[tuple[type, str]]:
    from parsefabric.aggregation import Aggregator
    from parsefabric.builtins.cli_output import CommandOutputBackend
    from parsefabric.builtins.code_detection import CodeDetector
    from parsefabric.codecs import AggregateCodec, JSONCodec
    from parsefabric.compression import Tokenizer
    from parsefabric.execution import ExecutionBackend
    from parsefabric.llm import LanguageModel
    from parsefabric.observability import ObservabilitySink
    from parsefabric.parser import Parser
    from parsefabric.partitioning import Partitioner
    from parsefabric.patterns import Pattern
    from parsefabric.registry import ParserRegistry

    return [
        (Parser, "check_parser"),
        (Pattern, "check_pattern"),
        (Aggregator, "check_aggregator"),
        (AggregateCodec, "check_codec"),
        (JSONCodec, "check_json_codec"),
        (Partitioner, "check_partitioner"),
        (ExecutionBackend, "check_execution_backend"),
        (ObservabilitySink, "check_observability_sink"),
        (LanguageModel, "check_language_model"),
        (ParserRegistry, "check_parser_registry"),
        (Tokenizer, "check_tokenizer"),
        (CodeDetector, "check_code_detector"),
        (CommandOutputBackend, "check_command_output_backend"),
    ]


def identify(extension: object) -> tuple[type, str]:
    for base, check in contract_checks():
        if isinstance(extension, base):
            return base, check
    raise TypeError(f"{type(extension).__name__} subclasses no ParseFabric extension point")


async def sample_events(text: str) -> Any:
    from parsefabric import ParseContext, ParseEngine
    from parsefabric.builtins import ApplicationLogParser

    result = await ParseEngine().parse(
        ApplicationLogParser(), text, ParseContext(source_id="sample")
    )
    if not result.events:
        raise UsageError("the input produced no events from ApplicationLogParser")
    return result.events


def required(value: Any, option: str, base: type) -> Any:
    if value is None or value == []:
        raise UsageError(f"checking a {base.__name__} needs {option}")
    return value


def expectations(pairs: list[str]) -> dict[str, str | None]:
    expected: dict[str, str | None] = {}
    for pair in pairs:
        text, separator, language = pair.rpartition("=")
        if not separator or not text:
            raise UsageError(f"expected TEXT=LANGUAGE, got {pair!r}")
        expected[text.replace("\\n", "\n")] = None if language == "none" else language
    return expected


async def check(extension: Any, base: type, name: str, arguments: argparse.Namespace) -> None:
    from parsefabric import ParseContext, testing
    from parsefabric.aggregation import EvidenceAggregator
    from parsefabric.builtins import ApplicationLogParser, JSONParser

    contract = getattr(testing, name)
    source = arguments.input.read_text(encoding="utf-8") if arguments.input else None
    if name == "check_parser":
        text = required(source, "--input FILE", base)
        await contract(extension, text, ParseContext(source_id=arguments.input.name))
    elif name == "check_pattern":
        matching = required(arguments.matching, "--matching TEXT", base)
        contract(extension, matching, required(arguments.other, "--other TEXT", base))
    elif name == "check_aggregator":
        await contract(extension, await sample_events(source or SAMPLE_LOG))
    elif name == "check_codec":
        events = await sample_events(source or SAMPLE_LOG)
        await contract(extension, await EvidenceAggregator().aggregate(events))
    elif name == "check_partitioner":
        lines = (source or SAMPLE_LOG).splitlines()
        await contract(extension, lines, capabilities=ApplicationLogParser().capabilities)
    elif name == "check_parser_registry":
        await contract(extension, [ApplicationLogParser(), JSONParser()])
    elif name == "check_code_detector":
        await contract(extension, expectations(required(arguments.expect, "--expect", base)))
    elif name == "check_command_output_backend":
        command = required(arguments.command, "--command NAME", base)
        await contract(extension, command, required(source, "--input FILE", base))
    else:
        await contract(extension)


def failure(error: BaseException) -> str:
    if isinstance(error, AssertionError):
        return str(error)
    return "".join(traceback.format_exception_only(error)).strip()


async def run(arguments: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        extension = await build(load_factory(arguments.factory))
        base, name = identify(extension)
    except Exception as error:
        message = f"cannot load {arguments.factory}: {type(error).__name__}: {error}"
        return 2, {"ok": False, "extension": None, "check": None, "error": message}
    outcome = {"extension": base.__name__, "check": name}
    try:
        await check(extension, base, name, arguments)
    except UsageError as error:
        return 2, {"ok": False, **outcome, "error": str(error)}
    except Exception as error:  # a broken contract, reported with its reason
        return 1, {"ok": False, **outcome, "error": failure(error)}
    return 0, {"ok": True, **outcome, "error": None}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("factory", help="MODULE:FACTORY returning a new extension")
    parser.add_argument("--input", type=Path, help="file with a representative input")
    parser.add_argument("--matching", help="text a Pattern must match")
    parser.add_argument("--other", help="text a Pattern must not match")
    parser.add_argument(
        "--expect", action="append", default=[], help="TEXT=LANGUAGE for a CodeDetector"
    )
    parser.add_argument("--command", help="command name for a CommandOutputBackend")
    parser.add_argument("--json", action="store_true", help="print one JSON object to stdout")
    parser.add_argument(
        "--path", type=Path, default=Path.cwd(), help="directory to import from (default: cwd)"
    )
    arguments = parser.parse_args()
    sys.path.insert(0, str(arguments.path.resolve()))
    code, outcome = asyncio.run(run(arguments))
    if arguments.json:
        print(json.dumps(outcome, indent=2))
    elif outcome["ok"]:
        print(f"PASS  {arguments.factory} ({outcome['extension']}) passes {outcome['check']}")
    else:
        status = "FAIL " if code == 1 else "ERROR"
        subject = f" ({outcome['extension']}) {outcome['check']}" if outcome["check"] else ""
        print(f"{status} {arguments.factory}{subject}\n      {outcome['error']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
