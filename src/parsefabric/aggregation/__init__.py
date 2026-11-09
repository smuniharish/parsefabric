"""Aggregation: lossless grouped evidence, lossy statistics and the `Aggregator` ABC."""

from parsefabric.aggregation.base import Aggregate, Aggregator, CountAggregate
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
