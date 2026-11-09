"""Offline language models for summarization and semantic-parser tests."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, override

from parsefabric.llm import ChatMessage, LanguageModel

if TYPE_CHECKING:
    from collections.abc import Sequence


class PromptLog:
    """Records every request a model receives, in call order."""

    def __init__(self) -> None:
        self.messages: list[tuple[ChatMessage, ...]] = []


class ScriptedModel(LanguageModel):
    """Replies with ``responses`` in order, cycling when exhausted."""

    def __init__(
        self, responses: Sequence[str], *, sleep: float = 0.0, log: PromptLog | None = None
    ) -> None:
        if not responses:
            raise ValueError("responses must not be empty")
        self.responses = tuple(responses)
        self.sleep = sleep
        self.log = log or PromptLog()
        self.i = 0

    @override
    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.log.messages.append(tuple(messages))
        # Always yield, as real providers await I/O.
        await asyncio.sleep(self.sleep)
        reply = self.responses[self.i]
        self.i = (self.i + 1) % len(self.responses)
        return reply


class SummaryModel(LanguageModel):
    """Drafts one claim per non-fence fact and approves every critique."""

    def __init__(
        self,
        *,
        label: str = "Evidence-based final summary",
        initial: str = "Initial interpretation",
        log: PromptLog | None = None,
    ) -> None:
        self.label = label
        self.initial = initial
        self.log = log or PromptLog()
        self._calls: list[tuple[str, str]] = []
        self._active = 0
        self._peak = 0

    @property
    def i(self) -> int:
        return len(self._calls)

    @override
    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.log.messages.append(tuple(messages))
        self._active += 1
        self._peak = max(self._peak, self._active)
        try:
            await asyncio.sleep(0.001)
            system, human = (message.content for message in messages)
            if "Draft structured claims" in system:
                stage = "draft"
                payload = json.loads(human.split("<evidence>\n")[1].split("\n</evidence>")[0])
                reply = json.dumps(
                    {
                        "claims": [
                            {
                                "text": self.label,
                                "evidence_ids": [fact["id"]],
                                "occurrences": fact["occurrences"],
                            }
                            for fact in payload["facts"]
                            if fact["event_type"] != "fence"
                        ]
                    }
                )
            elif "Critique structured claims" in system:
                stage = "critic"
                reply = '{"issues": []}'
            else:
                stage = "interpret"
                reply = self.initial
            self._calls.append((stage, human))
            return reply
        finally:
            self._active -= 1
