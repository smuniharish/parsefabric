"""Compare the size of a source with the output an application produced from it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "CompressionMetrics",
    "TokenEstimator",
    "estimate_tokens",
    "measure_compression",
]

type TokenEstimator = Callable[[str], int]


def estimate_tokens(text: str) -> int:
    """Approximate tokens as one per four UTF-8 bytes, rounded up.

    Args:
        text: Text to measure.

    Returns:
        The estimated token count.
    """
    return -(-len(text.encode("utf-8", errors="surrogatepass")) // 4)


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
        input_tokens: Estimated tokens in the source.
        output_tokens: Estimated tokens in the output.
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


def _measure(
    value: str | bytes, name: str, estimator: TokenEstimator | None
) -> tuple[int, int]:
    if isinstance(value, bytes):
        size = len(value)
        if estimator is None:
            return size, -(-size // 4)
        return size, estimator(value.decode("utf-8", errors="replace"))
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="surrogatepass")), (
            estimator or estimate_tokens
        )(value)
    raise TypeError(f"{name} must be str or bytes")


def measure_compression(
    source: str | bytes,
    output: str | bytes,
    *,
    token_estimator: TokenEstimator | None = None,
) -> CompressionMetrics:
    """Compare a source with the output an application produced from it.

    ParseFabric aggregates are in-memory objects; how they are encoded for
    storage or transport is the application's choice, so ``output`` is the
    already-encoded result, typically ``parser.serialize(aggregates)``.
    Verify losslessness with
    `parsefabric.engine.ParseEngine.materialize` before relying on the
    reduction.

    Args:
        source: The original input; text is measured as UTF-8.
        output: The encoded output.
        token_estimator: Function returning the token count of a text.
            Defaults to `estimate_tokens`. Bytes that are not valid
            UTF-8 are decoded with replacement characters before a custom
            estimator sees them.

    Returns:
        The size comparison.

    Raises:
        TypeError: If ``source`` or ``output`` is not text or bytes.
    """
    input_bytes, input_tokens = _measure(source, "source", token_estimator)
    output_bytes, output_tokens = _measure(output, "output", token_estimator)
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
