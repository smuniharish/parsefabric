"""Keep public imports, module layout and distribution metadata in sync."""

import ast
import pkgutil
import re
import subprocess
import sys
from importlib import import_module
from importlib.metadata import distribution
from pathlib import Path

import pytest

import parsefabric


@pytest.mark.parametrize(
    ("package", "module", "symbol"),
    [
        ("parser", "base", "Parser"),
        ("parser", "deterministic", "DeterministicParser"),
        ("parser", "semantic", "SemanticParser"),
        ("parser", "async_parser", "AsyncParser"),
        ("patterns", "base", "Pattern"),
        ("patterns", "match", "PatternMatch"),
        ("patterns", "regex", "RegexPattern"),
        ("patterns", "exact", "ExactPattern"),
        ("patterns", "predicate", "PredicatePattern"),
        ("patterns", "structured", "StructuredPattern"),
        ("builtins", "application_log", "ApplicationLogParser"),
        ("builtins", "cli_output", "CLIOutputParser"),
        ("builtins", "json_parser", "JSONParser"),
        ("builtins", "mixed_content", "MixedContentParser"),
        ("builtins", "python_traceback", "PythonTracebackParser"),
        ("builtins", "timestamped_log", "TimestampedLogParser"),
        ("execution", "base", "ExecutionBackend"),
        ("execution", "async_backend", "AsyncExecutionBackend"),
        ("execution", "thread_backend", "ThreadExecutionBackend"),
        ("execution", "process_backend", "ProcessExecutionBackend"),
    ],
)
def test_public_import_matches_implementation(package: str, module: str, symbol: str) -> None:
    implementation = getattr(import_module(f"parsefabric.{package}.{module}"), symbol)
    assert getattr(import_module(f"parsefabric.{package}"), symbol) is implementation
    assert implementation.__module__ == f"parsefabric.{package}.{module}"


PUBLIC_MODULES = {
    "aggregation",
    "aggregation.base",
    "aggregation.evidence",
    "aggregation.routing",
    "aggregation.statistical",
    "builtins",
    "builtins.application_log",
    "builtins.cli_output",
    "builtins.code_detection",
    "builtins.json_parser",
    "builtins.mixed_content",
    "builtins.python_traceback",
    "builtins.timestamped_log",
    "capabilities",
    "codecs",
    "compression",
    "engine",
    "errors",
    "execution",
    "execution.async_backend",
    "execution.base",
    "execution.process_backend",
    "execution.thread_backend",
    "integrations",
    "integrations.langchain",
    "llm",
    "models",
    "observability",
    "parser",
    "parser.async_parser",
    "parser.base",
    "parser.deterministic",
    "parser.semantic",
    "partitioning",
    "patterns",
    "patterns.base",
    "patterns.exact",
    "patterns.match",
    "patterns.predicate",
    "patterns.regex",
    "patterns.structured",
    "registry",
    "serialization",
    "summarization",
    "testing",
}


def test_public_module_set_is_exact() -> None:
    found = {
        module.name.removeprefix("parsefabric.")
        for module in pkgutil.walk_packages(parsefabric.__path__, "parsefabric.")
        if not any(part.startswith("_") for part in module.name.split("."))
    }
    assert found == PUBLIC_MODULES


def test_core_never_imports_an_agent_framework() -> None:
    script = (
        "import sys, parsefabric, parsefabric.summarization, parsefabric.llm;"
        "assert not [m for m in sys.modules if m.split('.')[0] in "
        "{'langchain', 'langchain_core', 'langgraph', 'openai'}], sorted(sys.modules)"
    )
    subprocess.run([sys.executable, "-c", script], check=True)


def test_extension_points_are_abstract_base_classes_not_protocols() -> None:
    root = Path(__file__).resolve().parents[2]
    offenders = [
        f"{path.relative_to(root)}:{node.lineno}"
        for folder in ("src", "examples", "benchmarks", "tests")
        for path in sorted((root / folder).rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == "Protocol" for alias in node.names)
    ]
    assert offenders == []


def _requirement_name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0]


def test_distribution_metadata_matches_declared_dependencies() -> None:
    metadata = distribution("parsefabric").metadata
    requirements = metadata.get_all("Requires-Dist") or []
    core = {_requirement_name(item) for item in requirements if "extra ==" not in item}
    extras = {
        name: {
            _requirement_name(item)
            for item in requirements
            if f"extra == '{name}'" in item or f'extra == "{name}"' in item
        }
        for name in metadata.get_all("Provides-Extra") or []
    }

    assert core == {
        "jc",
        "opentelemetry-api",
        "pydantic",
        "structlog",
        "tree-sitter",
        "tree-sitter-language-pack",
        "typing-extensions",
    }
    assert extras == {"langchain": {"langchain-core"}, "all": {"parsefabric"}}
    assert metadata["Version"] == parsefabric.__version__
