"""Keep public imports, module layout and distribution metadata in sync."""

import re
from importlib import import_module
from importlib.metadata import distribution

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
def test_public_import_matches_implementation(
    package: str, module: str, symbol: str
) -> None:
    implementation = getattr(import_module(f"parsefabric.{package}.{module}"), symbol)
    assert getattr(import_module(f"parsefabric.{package}"), symbol) is implementation
    assert implementation.__module__ == f"parsefabric.{package}.{module}"


def test_removed_compatibility_aliases_stay_removed() -> None:
    import parsefabric.patterns

    assert not hasattr(parsefabric.patterns, "CustomPattern")
    for module in ("log_sequences", "log_format", "integrations"):
        with pytest.raises(ModuleNotFoundError):
            import_module(f"parsefabric.{module}")


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
        "langchain-core",
        "langgraph",
        "msgspec",
        "opentelemetry-api",
        "pydantic",
        "structlog",
        "tree-sitter",
        "tree-sitter-language-pack",
    }
    assert extras == {"openai": {"langchain-openai"}}
    assert metadata["Version"] == parsefabric.__version__
