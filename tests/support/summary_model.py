"""Offline model implementing the structured summary protocol."""

import asyncio
import json
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr


class SummaryModel(BaseChatModel):
    label: str = "Evidence-based final summary"
    initial: str = "Initial interpretation"
    _calls: list[tuple[str, str]] = PrivateAttr(default_factory=list)
    _active: int = PrivateAttr(default=0)
    _peak: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "structured-summary-fixture"

    @property
    def i(self) -> int:
        return len(self._calls)

    def _generate(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> ChatResult:
        raise NotImplementedError

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._active += 1
        self._peak = max(self._peak, self._active)
        try:
            await asyncio.sleep(0.001)
            system, human = (str(message.content) for message in messages)
            if "Draft structured claims" in system:
                stage = "draft"
                payload = json.loads(
                    human.split("<evidence>\n")[1].split("\n</evidence>")[0]
                )
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
            return ChatResult(generations=[ChatGeneration(message=AIMessage(reply))])
        finally:
            self._active -= 1
