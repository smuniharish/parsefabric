"""Shared UTF-8 line framing for text parsers."""

from __future__ import annotations

import re
from collections.abc import Iterator

_LINE_ENDINGS = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")


def iter_text_lines(text: str) -> Iterator[tuple[str, int]]:
    """Yield each line and its UTF-8 width, including its terminator, lazily.

    Lines are split on the same boundaries as `str.splitlines`; the
    yielded text excludes the terminator.

    Raises:
        UnicodeEncodeError: If the text contains lone surrogates.
    """
    start = 0
    if text.isascii():
        for boundary in _LINE_ENDINGS.finditer(text):
            end = boundary.end()
            yield text[start : boundary.start()], end - start
            start = end
        if start < len(text):
            yield text[start:], len(text) - start
        return
    for boundary in _LINE_ENDINGS.finditer(text):
        end = boundary.end()
        yield text[start : boundary.start()], len(text[start:end].encode("utf-8"))
        start = end
    if start < len(text):
        yield text[start:], len(text[start:].encode("utf-8"))
