"""Named, prioritized rules that recognize a value and turn matches into events."""

from __future__ import annotations

from parsefabric.patterns.base import Pattern
from parsefabric.patterns.exact import ExactPattern
from parsefabric.patterns.match import PatternMatch
from parsefabric.patterns.predicate import PredicatePattern
from parsefabric.patterns.regex import RegexPattern
from parsefabric.patterns.structured import StructuredPattern

__all__ = [
    "ExactPattern",
    "Pattern",
    "PatternMatch",
    "PredicatePattern",
    "RegexPattern",
    "StructuredPattern",
]
