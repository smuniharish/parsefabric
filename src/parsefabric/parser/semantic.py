"""Provider-neutral semantic parser abstraction."""

from __future__ import annotations

from parsefabric.llm import LanguageModel
from parsefabric.parser.async_parser import AsyncParser
from parsefabric.parser.base import AggregateT_co


class SemanticParser(AsyncParser[AggregateT_co]):
    """Base class for user-owned, provider-neutral semantic parsing.

    A semantic parser interprets input with application-supplied logic, such
    as a language model. ParseFabric does not bundle or select a provider:
    inject any `LanguageModel` as ``model`` and call it from `parse`. Output
    is not assumed to be reproducible, so the default aggregator retains
    every event instead of re-parsing the source.

    Args:
        name: Non-empty parser name.
        version: Non-empty parser version.
        model: Optional model the parser interprets input with.

    Raises:
        TypeError: If ``model`` is not a `LanguageModel`.
        ValueError: If ``name`` or ``version`` is empty or not a string.
    """

    def __init__(
        self, *, name: str, version: str = "1", model: LanguageModel | None = None
    ) -> None:
        super().__init__(name=name, version=version)
        if model is not None and not isinstance(model, LanguageModel):
            raise TypeError("model must be a LanguageModel")
        self._model = model

    @property
    def model(self) -> LanguageModel | None:
        """The injected language model, if any."""
        return self._model
