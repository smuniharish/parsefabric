"""ParseFabric: composable parsers with traceable, losslessly aggregated evidence.

The package root exports the engine, the result models, the parser
contracts, aggregation types and errors. Built-in parsers live in
`parsefabric.builtins`, patterns in `parsefabric.patterns`,
execution backends in `parsefabric.execution` and lifecycle sinks in
`parsefabric.observability`.
"""

from parsefabric._json import MAX_JSON_DEPTH
from parsefabric.aggregation import (
    Aggregate,
    Aggregator,
    EvidenceAggregate,
    EvidenceAggregator,
    EvidenceEntry,
    EvidenceGroup,
    RoutingAggregator,
)
from parsefabric.capabilities import ParserCapabilities
from parsefabric.compression import CompressionMetrics, measure_compression
from parsefabric.engine import ParseEngine
from parsefabric.errors import (
    CapabilityError,
    ConfigurationError,
    DuplicateParserError,
    IntegrityError,
    ParseError,
    ParseFabricError,
    ParseIssue,
    RegistryError,
    SerializationError,
    SummaryValidationError,
)
from parsefabric.models import (
    Evidence,
    ParseContext,
    ParsedEvent,
    ParseResult,
    PatternStatistic,
)
from parsefabric.parser import AsyncParser, DeterministicParser, Parser, SemanticParser

__version__ = "0.1.0"

__all__ = [
    "MAX_JSON_DEPTH",
    "Aggregate",
    "Aggregator",
    "AsyncParser",
    "CapabilityError",
    "CompressionMetrics",
    "ConfigurationError",
    "DeterministicParser",
    "DuplicateParserError",
    "Evidence",
    "EvidenceAggregate",
    "EvidenceAggregator",
    "EvidenceEntry",
    "EvidenceGroup",
    "IntegrityError",
    "ParseContext",
    "ParseEngine",
    "ParseError",
    "ParseFabricError",
    "ParseIssue",
    "ParseResult",
    "ParsedEvent",
    "Parser",
    "ParserCapabilities",
    "PatternStatistic",
    "RegistryError",
    "RoutingAggregator",
    "SemanticParser",
    "SerializationError",
    "SummaryValidationError",
    "__version__",
    "measure_compression",
]
