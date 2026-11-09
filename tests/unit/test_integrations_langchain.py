"""LangChain and LangGraph adapters."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake import FakeListLLM
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from parsefabric.builtins import ApplicationLogParser
from parsefabric.engine import ParseEngine
from parsefabric.integrations.langchain import (
    LangChainLanguageModel,
    parser_node,
    parser_tool,
)
from parsefabric.llm import ChatMessage
from parsefabric.models import ParseResult
from parsefabric.summarization import EvidenceSummarizer

LOG = "2026-10-01T08:00:02Z ERROR database timeout\n"


class _EchoChat(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "echo"

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        reply = " | ".join(f"{message.type}:{message.content}" for message in messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(reply))])


async def test_chat_model_receives_role_mapped_messages() -> None:
    chat = _EchoChat()
    model = LangChainLanguageModel(chat)
    reply = await model.complete(
        (
            ChatMessage("system", "rules"),
            ChatMessage("user", "question"),
            ChatMessage("assistant", "draft"),
        )
    )
    assert reply == "system:rules | human:question | ai:draft"
    assert model.model is chat
    assert model.name == "langchain:_EchoChat"


async def test_text_models_are_supported_and_drive_the_summarizer() -> None:
    model = LangChainLanguageModel(FakeListLLM(responses=["plain text"]))
    assert await model.complete((ChatMessage("user", "hi"),)) == "plain text"
    assert EvidenceSummarizer(model).model is model


def test_non_langchain_models_are_rejected() -> None:
    with pytest.raises(TypeError, match="BaseLanguageModel"):
        # pyrefly: ignore[bad-argument-type]
        LangChainLanguageModel(object())
    with pytest.raises(TypeError, match="Parser"):
        # pyrefly: ignore[bad-argument-type]
        parser_tool(object())
    with pytest.raises(TypeError, match="Parser"):
        # pyrefly: ignore[bad-argument-type]
        parser_node(object())


async def test_parser_tool_returns_the_serialized_result() -> None:
    tool = parser_tool(ApplicationLogParser())
    assert tool.name == "parse_application_log"
    assert "'application-log' parser" in tool.description
    output = await tool.ainvoke({"text": LOG, "source_id": "svc.log"})
    result = ParseResult.from_dict(output)
    assert result.events
    assert {event.evidence.source_id for event in result.events} == {"svc.log"}

    named = parser_tool(
        ApplicationLogParser(), engine=ParseEngine(), name="logs", description="Parse logs."
    )
    assert (named.name, named.description) == ("logs", "Parse logs.")
    assert ParseResult.from_dict(await named.ainvoke({"text": LOG})).events


async def test_parser_node_reads_and_writes_state_keys() -> None:
    node = parser_node(ApplicationLogParser(), input_key="log", output_key="parsed")
    update = await node({"log": LOG})
    assert update["parsed"].events
    assert update["parsed"].events[0].evidence.source_id is None

    with_source = parser_node(ApplicationLogParser(), source_id_key="source")
    update = await with_source({"text": LOG, "source": "svc.log"})
    assert update["parse_result"].events[0].evidence.source_id == "svc.log"


def test_missing_extra_names_the_install_command() -> None:
    script = (
        "import sys; sys.modules['langchain_core'] = None\n"
        "try:\n"
        "    import parsefabric.integrations.langchain\n"
        "except ImportError as error:\n"
        "    print(error)\n"
    )
    output = subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    ).stdout
    assert 'pip install "parsefabric[langchain]"' in output
