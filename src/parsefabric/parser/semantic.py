"""Provider-neutral semantic parser abstraction."""

from __future__ import annotations

from parsefabric.parser.async_parser import AsyncParser


class SemanticParser(AsyncParser):
    """Base class for user-owned, provider-neutral semantic parsing.

    A semantic parser interprets input with application-supplied logic, such
    as a language model. ParseFabric does not bundle or select a provider.
    Its output is not assumed to be reproducible, so package-managed
    aggregation retains every event instead of re-parsing the source.
    """
