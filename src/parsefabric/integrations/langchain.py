"""LangChain and LangGraph adapters.

Requires ``pip install "parsefabric[langchain]"``.

* `LangChainLanguageModel` lets any LangChain chat or text model drive
  `EvidenceSummarizer` and `SemanticParser`.
* `parser_tool` exposes a parser as a LangChain tool for agents.
* `parser_node` turns a parser into an async LangGraph node.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, override

from parsefabric.engine import ParseEngine
from parsefabric.llm import ChatMessage, LanguageModel
from parsefabric.models import ParseContext
from parsefabric.parser.base import Parser

try:
    from langchain_core.language_models import BaseLanguageModel
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.tools import StructuredTool
except ImportError as error:  # pragma: no cover - requires an environment without the extra
    raise ImportError(
        'parsefabric.integrations.langchain requires: pip install "parsefabric[langchain]"'
    ) from error
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from parsefabric.aggregation.base import Aggregate
    from parsefabric.models import JSONValue, ParseResult

__all__ = ["LangChainLanguageModel", "parser_node", "parser_tool"]

_MESSAGE_TYPES: dict[str, type[BaseMessage]] = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


class LangChainLanguageModel(LanguageModel):
    """A `LanguageModel` backed by a LangChain chat or text model.

    Args:
        model: Any LangChain ``BaseLanguageModel``, for example ``ChatOpenAI``
            or the result of ``init_chat_model``.

    Raises:
        TypeError: If ``model`` is not a LangChain language model.
    """

    def __init__(self, model: BaseLanguageModel[Any]) -> None:
        if not isinstance(model, BaseLanguageModel):
            raise TypeError("model must be a LangChain BaseLanguageModel")
        self._model = model
        self._output = StrOutputParser()

    @property
    def model(self) -> BaseLanguageModel[Any]:
        """The wrapped LangChain model."""
        return self._model

    @property
    @override
    def name(self) -> str:
        return f"langchain:{type(self._model).__name__}"

    @override
    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        reply = await self._model.ainvoke(
            [_MESSAGE_TYPES[message.role](content=message.content) for message in messages]
        )
        return await self._output.ainvoke(reply)


class _ParseInput(BaseModel):
    text: str = Field(description="Text to parse.")
    source_id: str | None = Field(
        default=None, description="Optional identifier of the source, such as a file name."
    )


def parser_tool(
    parser: Parser[Aggregate],
    *,
    engine: ParseEngine | None = None,
    name: str | None = None,
    description: str | None = None,
) -> StructuredTool:
    """Expose ``parser`` as an async LangChain tool.

    The tool parses the ``text`` argument through ``engine`` and returns the
    serialized `ParseResult`, including evidence, as a dictionary.

    Args:
        parser: Parser the tool runs.
        engine: Engine that applies limits and observability; a default
            `ParseEngine` otherwise.
        name: Tool name; ``parse_<parser name>`` by default.
        description: Tool description shown to the model.

    Returns:
        A LangChain ``StructuredTool``.

    Raises:
        TypeError: If ``parser`` is not a `Parser`.
    """
    if not isinstance(parser, Parser):
        raise TypeError("parser must be a Parser")
    runner = engine or ParseEngine()

    async def parse(text: str, source_id: str | None = None) -> dict[str, JSONValue]:
        result = await runner.parse(parser, text, ParseContext(source_id=source_id))
        return result.to_dict()

    return StructuredTool.from_function(
        coroutine=parse,
        name=name or f"parse_{parser.name}".replace("-", "_"),
        description=description
        or f"Parse text with the {parser.name!r} parser into structured events with evidence.",
        args_schema=_ParseInput,
    )


def parser_node[StateT: Mapping[str, Any]](
    parser: Parser[Aggregate],
    *,
    engine: ParseEngine | None = None,
    input_key: str = "text",
    output_key: str = "parse_result",
    source_id_key: str | None = None,
) -> Callable[[StateT], Awaitable[dict[str, ParseResult]]]:
    """Return an async LangGraph node that parses one state field.

    Args:
        parser: Parser the node runs.
        engine: Engine that applies limits and observability; a default
            `ParseEngine` otherwise.
        input_key: State key holding the text or bytes to parse.
        output_key: State key the `ParseResult` is written to.
        source_id_key: Optional state key holding the source identifier.

    Returns:
        A node function for ``StateGraph.add_node``.

    Raises:
        TypeError: If ``parser`` is not a `Parser`.
    """
    if not isinstance(parser, Parser):
        raise TypeError("parser must be a Parser")
    runner = engine or ParseEngine()

    async def node(state: StateT) -> dict[str, ParseResult]:
        source_id = state.get(source_id_key) if source_id_key is not None else None
        result = await runner.parse(parser, state[input_key], ParseContext(source_id=source_id))
        return {output_key: result}

    return node
