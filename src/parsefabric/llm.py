"""Provider-neutral language-model interface.

ParseFabric never imports a model provider. Components that need a model,
such as `EvidenceSummarizer` and `SemanticParser`, accept any
`LanguageModel`. Implement `complete` to call your provider, or use an
adapter such as `parsefabric.integrations.langchain.LangChainLanguageModel`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["ChatMessage", "ChatRole", "LanguageModel"]

type ChatRole = Literal["system", "user", "assistant"]
_ROLES = frozenset({"system", "user", "assistant"})


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One message of a chat-style model request.

    Attributes:
        role: ``"system"``, ``"user"`` or ``"assistant"``.
        content: Message text.

    Raises:
        ValueError: If ``role`` is unknown or ``content`` is not a string.
    """

    role: ChatRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in _ROLES:
            raise ValueError(f"role must be one of {sorted(_ROLES)}")
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")


class LanguageModel(ABC):
    """A text-completion model used by ParseFabric components.

    Implementations call a provider and return the reply text. They own
    transport concerns such as authentication, retries and rate limits;
    callers own the overall time budget.
    """

    @property
    def name(self) -> str:
        """Identifier used in logs and diagnostics; the class name by default."""
        return type(self).__name__

    @abstractmethod
    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        """Return the model's reply to ``messages``.

        Args:
            messages: Conversation, normally a system message followed by a
                user message.

        Returns:
            The reply text.
        """
