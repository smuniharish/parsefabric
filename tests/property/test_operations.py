"""Stateful and operational properties: registries, spans, metrics and review."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    consumes,
    invariant,
    rule,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from parsefabric._summary_review import Fact, check_claims
from parsefabric.compression import estimate_tokens, measure_compression
from parsefabric.errors import ConfigurationError, RegistryError
from parsefabric.observability import LifecycleEvent, OpenTelemetryObservabilitySink
from parsefabric.parser import DeterministicParser
from parsefabric.patterns import RegexPattern
from parsefabric.registry import ParserRegistry
from tests.support.strategies import UNICODE

PATTERN_NAMES = st.sampled_from(["a", "b", "c", "d", "e"])


class PatternRegistryMachine(RuleBasedStateMachine):
    """A parser's pattern set behaves like an ordered, uniquely keyed map."""

    def __init__(self) -> None:
        super().__init__()
        self.parser = DeterministicParser([], name="machine")
        self.model: dict[str, int] = {}

    @rule(name=PATTERN_NAMES, priority=st.integers(-3, 3), replace=st.booleans())
    def register(self, name: str, priority: int, replace: bool) -> None:
        pattern = RegexPattern(name, name, priority=priority)
        if name in self.model and not replace:
            try:
                self.parser.register_pattern(pattern)
            except ConfigurationError:
                return
            raise AssertionError("duplicate pattern accepted")
        self.parser.register_pattern(pattern, replace=replace)
        self.model[name] = priority

    @rule(name=PATTERN_NAMES)
    def unregister(self, name: str) -> None:
        if name not in self.model:
            try:
                self.parser.unregister_pattern(name)
            except ConfigurationError:
                return
            raise AssertionError("missing pattern removed")
        removed = self.parser.unregister_pattern(name)
        assert (removed.name, removed.priority) == (name, self.model.pop(name))

    @invariant()
    def patterns_follow_priority_then_name(self) -> None:
        expected = sorted(self.model.items(), key=lambda item: (-item[1], item[0]))
        actual = [(item.name, item.priority) for item in self.parser.patterns]
        assert actual == expected


class ParserRegistryMachine(RuleBasedStateMachine):
    """A registry behaves like a map from parser names to parser instances."""

    registered = Bundle("registered")

    def __init__(self) -> None:
        super().__init__()
        self.registry = ParserRegistry()
        self.model: dict[str, DeterministicParser] = {}

    @rule(target=registered, name=PATTERN_NAMES)
    def register(self, name: str) -> str:
        parser = DeterministicParser([], name=name)
        if name in self.model:
            self.registry.register(parser, replace=True)
        else:
            self.registry.register(parser)
        self.model[name] = parser
        return name

    @rule(name=consumes(registered))
    def unregister(self, name: str) -> None:
        if name in self.model:
            assert self.registry.unregister(name) is self.model.pop(name)
        else:
            try:
                self.registry.unregister(name)
            except RegistryError:
                return
            raise AssertionError("missing parser unregistered")

    @invariant()
    def names_and_lookups_match(self) -> None:
        assert self.registry.names() == tuple(sorted(self.model))
        for name, parser in self.model.items():
            assert self.registry.get(name) is parser
            assert self.registry.metadata(name).name == name


TestPatternRegistry = PatternRegistryMachine.TestCase
TestParserRegistry = ParserRegistryMachine.TestCase


@dataclass
class _Operation:
    kind: str
    failed: bool
    children: list[_Operation] = field(default_factory=list)


OPERATIONS = st.recursive(
    st.builds(
        _Operation,
        st.sampled_from(["parse", "execution", "aggregation", "materialize"]),
        st.booleans(),
    ),
    lambda children: st.builds(
        _Operation,
        st.sampled_from(["parse", "execution", "aggregation", "materialize"]),
        st.booleans(),
        st.lists(children, max_size=3),
    ),
    max_leaves=10,
)
_EVENTS = {
    "parse": ("ParserSelected", "ParseCompleted", "ParseFailed"),
    "execution": ("ExecutionSubmitted", "ExecutionCompleted", "ExecutionFailed"),
    "aggregation": ("AggregationStarted", "AggregationCompleted", "AggregationFailed"),
    "materialize": ("MaterializeStarted", "MaterializeCompleted", "MaterializeFailed"),
}


def _emit(sink: OpenTelemetryObservabilitySink, operation: _Operation) -> int:
    start, completed, failed = _EVENTS[operation.kind]
    sink.emit(LifecycleEvent(start))
    total = 1 + sum(_emit(sink, child) for child in operation.children)
    sink.emit(
        LifecycleEvent(
            failed if operation.failed else completed,
            attributes={"error_type": "Boom"} if operation.failed else {},
        )
    )
    return total


@given(st.lists(OPERATIONS, min_size=1, max_size=3))
def test_spans_open_and_close_in_matching_nested_pairs(
    operations: list[_Operation],
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OpenTelemetryObservabilitySink(provider.get_tracer("test"))
    total = sum(_emit(sink, operation) for operation in operations)
    spans = exporter.get_finished_spans()
    assert len(spans) == total
    by_id = {}
    for span in spans:
        assert span.context is not None
        by_id[span.context.span_id] = span
    for span in spans:
        assert span.end_time is not None
        assert span.start_time is not None
        assert span.start_time <= span.end_time
        failed = any(event.name.endswith("Failed") for event in span.events)
        assert (span.status.status_code is StatusCode.ERROR) == failed
        if span.parent is not None and span.parent.span_id in by_id:
            parent = by_id[span.parent.span_id]
            assert parent.start_time is not None
            assert parent.start_time <= span.start_time


@given(st.text(UNICODE, max_size=200) | st.binary(max_size=200))
def test_compression_metrics_are_consistent(source: str | bytes) -> None:
    output = source[: len(source) // 2]
    metrics = measure_compression(source, output)
    size = len(source if isinstance(source, bytes) else source.encode("utf-8"))
    assert metrics.input_bytes == size
    assert metrics.bytes_saved == metrics.input_bytes - metrics.output_bytes
    assert metrics.input_tokens == math.ceil(size / 4)
    assert metrics.tokens_saved == metrics.input_tokens - metrics.output_tokens
    if size:
        assert metrics.reduction_percent == 100 * metrics.bytes_saved / size
    else:
        assert metrics.reduction_percent is None
    if isinstance(source, str):
        assert metrics.input_tokens == estimate_tokens(source)


_FACTS = (
    Fact("e0", "s", "error", "ERROR", "timeout 5", 2, (1, 2), (), False),
    Fact("e1", "s", "log", "WARN", "slow", 1, (3,), (), False),
    Fact("e2", "s", "fence", None, {"text": "```"}, 1, (4,), (), False),
)


@given(st.text(max_size=300))
def test_claim_checks_never_fail_on_arbitrary_text(text: str) -> None:
    claims, issues = check_claims(text, _FACTS)
    assert claims is not None or issues


@given(
    st.lists(
        st.fixed_dictionaries(
            {
                "text": st.text(min_size=1, max_size=40),
                "evidence_ids": st.lists(
                    st.sampled_from(["e0", "e1", "e2", "e9"]), min_size=1, max_size=3
                ),
                "context_ids": st.lists(
                    st.sampled_from(["e0", "e1", "e2"]), max_size=2
                ),
                "occurrences": st.integers(min_value=1, max_value=5),
            }
        ),
        max_size=4,
    )
)
def test_claim_checks_accept_only_grounded_complete_claims(
    claims: list[dict[str, object]],
) -> None:
    parsed, issues = check_claims(json.dumps({"claims": claims}), _FACTS)
    assert parsed is not None
    cited = [
        identifier
        for claim in claims
        for identifier in claim["evidence_ids"]  # type: ignore[union-attr]
    ]
    if not issues:
        assert {"e0", "e1"} <= set(cited)
        assert "e9" not in cited
        assert "e2" not in cited
        assert len(cited) == len(set(cited))
