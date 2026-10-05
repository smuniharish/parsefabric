"""Package-managed aggregation: lossless grouped evidence and lossy statistics."""

from parsefabric.aggregation.base import Aggregate, Aggregator, CountAggregate
from parsefabric.aggregation.codec import FORMAT
from parsefabric.aggregation.evidence import (
    EvidenceAggregate,
    EvidenceAggregator,
    EvidenceEntry,
    EvidenceGroup,
    canonical_event,
    default_event_message,
)
from parsefabric.aggregation.routing import RoutingAggregator
from parsefabric.aggregation.statistical import EventAccumulator, EventAggregator

__all__ = [
    "FORMAT",
    "Aggregate",
    "Aggregator",
    "CountAggregate",
    "EventAccumulator",
    "EventAggregator",
    "EvidenceAggregate",
    "EvidenceAggregator",
    "EvidenceEntry",
    "EvidenceGroup",
    "RoutingAggregator",
    "canonical_event",
    "default_event_message",
]
