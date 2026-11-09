"""Compare the size of a source with the output an application produced from it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import override

__all__ = [
    "DEFAULT_TOKENIZER",
    "ApproximateTokenizer",
    "CompressionMetrics",
    "Tokenizer",
    "measure_compression",
]


class Tokenizer(ABC):
    """Count the tokens of a text, for example with a model's own tokenizer.

    Subclasses implement `count`. `count_bytes` decodes UTF-8 with
    replacement characters and counts the text; override it to count raw
    bytes directly.
    """

    @abstractmethod
    async def count(self, text: str) -> int:
        """Return the number of tokens in ``text``."""

    async def count_bytes(self, data: bytes) -> int:
        """Return the number of tokens in encoded ``data``."""
        return await self.count(data.decode("utf-8", errors="replace"))


class ApproximateTokenizer(Tokenizer):
    """Approximate tokens from the UTF-8 size, rounded up.

    Args:
        bytes_per_token: Average number of bytes in one token.

    Raises:
        ValueError: If ``bytes_per_token`` is not a positive integer.
    """

    def __init__(self, bytes_per_token: int = 4) -> None:
        if (
            isinstance(bytes_per_token, bool)
            or not isinstance(bytes_per_token, int)
            or bytes_per_token < 1
        ):
            raise ValueError("bytes_per_token must be a positive integer")
        self._bytes_per_token = bytes_per_token

    @property
    def bytes_per_token(self) -> int:
        """Average number of bytes in one token."""
        return self._bytes_per_token

    @override
    async def count(self, text: str) -> int:
        return await self.count_bytes(text.encode("utf-8", errors="surrogatepass"))

    @override
    async def count_bytes(self, data: bytes) -> int:
        return -(-len(data) // self._bytes_per_token)


DEFAULT_TOKENIZER = ApproximateTokenizer()
"""One token per four UTF-8 bytes; the default of `measure_compression`."""


def _percent(saved: int, total: int) -> float | None:
    return 100 * saved / total if total else None


@dataclass(frozen=True, slots=True)
class CompressionMetrics:
    """Signed size comparison; negative savings mean the output grew.

    Attributes:
        input_bytes: Size of the source in bytes (UTF-8 for text).
        output_bytes: Size of the output in bytes (UTF-8 for text).
        bytes_saved: ``input_bytes - output_bytes``.
        reduction_percent: Bytes saved as a percentage of the input, or
            ``None`` for an empty input.
        input_tokens: Tokens in the source.
        output_tokens: Tokens in the output.
        tokens_saved: ``input_tokens - output_tokens``.
        token_reduction_percent: Tokens saved as a percentage of the input
            tokens, or ``None`` when the input has no tokens.
    """

    input_bytes: int
    output_bytes: int
    bytes_saved: int
    reduction_percent: float | None
    input_tokens: int
    output_tokens: int
    tokens_saved: int
    token_reduction_percent: float | None


async def _measure(value: str | bytes, name: str, tokenizer: Tokenizer) -> tuple[int, int]:
    if isinstance(value, bytes):
        return len(value), await tokenizer.count_bytes(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="surrogatepass")), await tokenizer.count(value)
    raise TypeError(f"{name} must be str or bytes")


async def measure_compression(
    source: str | bytes,
    output: str | bytes,
    *,
    tokenizer: Tokenizer = DEFAULT_TOKENIZER,
) -> CompressionMetrics:
    """Compare a source with the output an application produced from it.

    ParseFabric aggregates are in-memory objects; how they are encoded for
    storage or transport is the application's choice, so ``output`` is the
    already-encoded result, typically ``await engine.serialize(aggregates)``.
    Verify losslessness with `parsefabric.engine.ParseEngine.materialize`
    before relying on the reduction.

    Args:
        source: The original input; text is measured as UTF-8.
        output: The encoded output.
        tokenizer: Counts tokens; defaults to `DEFAULT_TOKENIZER`.

    Returns:
        The size comparison.

    Raises:
        TypeError: If ``source`` or ``output`` is not text or bytes, or
            ``tokenizer`` is not a `Tokenizer`.
    """
    if not isinstance(tokenizer, Tokenizer):
        raise TypeError("tokenizer must be a Tokenizer")
    input_bytes, input_tokens = await _measure(source, "source", tokenizer)
    output_bytes, output_tokens = await _measure(output, "output", tokenizer)
    saved = input_bytes - output_bytes
    tokens_saved = input_tokens - output_tokens
    return CompressionMetrics(
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        bytes_saved=saved,
        reduction_percent=_percent(saved, input_bytes),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokens_saved=tokens_saved,
        token_reduction_percent=_percent(tokens_saved, input_tokens),
    )
