"""ParseFabric: composable parsers with traceable, losslessly aggregated evidence.

The package root exports the engine, the result models, the parser
contracts, aggregation types, the language-model contract and errors.
Built-in parsers live in `parsefabric.builtins`, patterns in
`parsefabric.patterns`, execution backends in `parsefabric.execution`,
lifecycle sinks in `parsefabric.observability`, partitioners in
`parsefabric.partitioning`, summaries in `parsefabric.summarization` and
framework adapters in `parsefabric.integrations`.
"""

from importlib.metadata import version

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
from parsefabric.codecs import AggregateCodec, EvidenceCodec, JSONCodec, StrictJSONCodec
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
from parsefabric.llm import ChatMessage, LanguageModel
from parsefabric.models import (
    Evidence,
    ParseContext,
    ParsedEvent,
    ParseResult,
    PatternStatistic,
)
from parsefabric.parser import AsyncParser, DeterministicParser, Parser, SemanticParser

__version__ = version("parsefabric")

__all__ = [
    "MAX_JSON_DEPTH",
    "Aggregate",
    "AggregateCodec",
    "Aggregator",
    "AsyncParser",
    "CapabilityError",
    "ChatMessage",
    "CompressionMetrics",
    "ConfigurationError",
    "DeterministicParser",
    "DuplicateParserError",
    "Evidence",
    "EvidenceAggregate",
    "EvidenceAggregator",
    "EvidenceCodec",
    "EvidenceEntry",
    "EvidenceGroup",
    "IntegrityError",
    "JSONCodec",
    "LanguageModel",
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
    "StrictJSONCodec",
    "SummaryValidationError",
    "__version__",
    "measure_compression",
]
