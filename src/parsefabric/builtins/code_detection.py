"""Source-code detection with tree-sitter grammars.

A block of text is code in a language when that language's grammar parses it
without errors *and* every top-level node is a real construct (a definition,
declaration, statement, call, or assignment). Bare words, literals, JSON-like
values, and ``key: value`` lines also parse in several grammars, so they are
not code on their own.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterator, Sequence

import tree_sitter_language_pack as language_pack
from tree_sitter import Node, Parser

DEFAULT_CODE_LANGUAGES: tuple[str, ...] = (
    "python",
    "javascript",
    "typescript",
    "java",
    "go",
    "rust",
    "c",
    "cpp",
    "sql",
)
"""Grammars that reject ordinary prose; checked in this order."""

# Grammars that accept plain sentences (``word word`` is a shell command, a Ruby
# call, or PHP template text), so they cannot tell code from prose.
_PROSE_ACCEPTING = frozenset({"bash", "shell", "sh", "zsh", "ruby", "php"})
_CACHE_SIZE = 4096
# Long blocks rarely repeat; caching only short texts bounds cache memory.
_CACHEABLE_LENGTH = 1024
_WRAPPERS = frozenset({"expression_statement"})
_STRONG_SUFFIXES = (
    "_definition",
    "_declaration",
    "_statement",
    "_item",
    "_directive",
    "_clause",
    "call",
    "call_expression",
    "assignment",
    "assignment_expression",
)
_WEAK = frozenset({"labeled_statement", "empty_statement", "expression_statement"})
_CALLS = frozenset({"call", "call_expression"})
_ASSIGNMENTS = frozenset(
    {"assignment", "assignment_expression", "assignment_statement"}
)
_COMMENTS = frozenset({"comment", "line_comment", "block_comment"})
_SQL_STATEMENTS = frozenset(
    {
        "select",
        "insert",
        "update",
        "delete",
        "create_table",
        "create_index",
        "create_view",
        "alter_table",
        "drop_table",
        "merge",
    }
)


def _walk(node: Node) -> Iterator[Node]:
    """Yield a subtree in document order without recursion; deep input is safe."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _first_keyword(node: Node) -> Node | None:
    return next(
        (item for item in _walk(node) if item.type.startswith("keyword_")), None
    )


def _has_call(node: Node) -> bool:
    return any(item.type in _CALLS for item in _walk(node))


def _is_plain_assignment(node: Node) -> bool:
    """``key=value`` alone is a logfmt field as often as code, so it is weak."""
    if node.type in _WRAPPERS and node.named_child_count == 1:
        node = node.named_children[0]
    return node.type in _ASSIGNMENTS and not _has_call(node)


def _is_construct(node: Node, language: str, text: str) -> bool:
    if language == "sql":
        if node.type != "statement" or not any(
            child.type in _SQL_STATEMENTS for child in node.named_children
        ):
            return False
        # ``select the order`` is valid SQL; real statements are terminated or
        # written with upper-case keywords.
        keyword = _first_keyword(node)
        return text.rstrip().endswith(";") or (
            keyword is not None and (keyword.text or b"").isupper()
        )
    if node.type in _WRAPPERS and node.named_child_count == 1:
        node = node.named_children[0]
    if node.type in _WEAK or node.named_child_count == 0:
        return False  # A lone ``pass``/``continue`` reads as a word, not code.
    if node.type == "assignment" and node.child_by_field_name("right") is None:
        return False  # ``status: ok`` is a Python annotation, not code.
    if node.type in _CALLS:
        function = node.child_by_field_name("function")
        arguments = node.child_by_field_name("arguments")
        if (
            function is not None
            and arguments is not None
            and function.end_byte != arguments.start_byte
        ):
            return False  # ``Total (approx)`` is prose, not a call.
    return node.type.endswith(_STRONG_SUFFIXES) or node.type.startswith("preproc_")


class CodeDetector:
    """Detect which configured grammar, if any, parses a text block as code.

    Grammars are tried in the configured order. Results for short texts are
    kept in a bounded least-recently-used cache shared by all threads; each
    thread uses its own tree-sitter parsers. Missing grammars are downloaded
    when the detector is created.

    Args:
        languages: tree-sitter language names. Grammars that accept ordinary
            prose (``bash``, ``shell``, ``sh``, ``zsh``, ``ruby``, ``php``)
            are rejected.

    Raises:
        TypeError: If ``languages`` is not a sequence of names.
        ValueError: If a language is unknown or accepts prose.
    """

    def __init__(self, languages: Sequence[str] = DEFAULT_CODE_LANGUAGES) -> None:
        if isinstance(languages, str) or not all(
            isinstance(language, str) and language for language in languages
        ):
            raise TypeError("code languages must be a sequence of language names")
        selected = tuple(dict.fromkeys(languages))
        for language in selected:
            if language in _PROSE_ACCEPTING:
                raise ValueError(
                    f"{language!r} parses ordinary prose, so it cannot detect code"
                )
            if not language_pack.has_language(language):
                raise ValueError(f"unknown tree-sitter language: {language!r}")
        self._languages = selected
        self._local = threading.local()
        self._cache: OrderedDict[str, str | None] = OrderedDict()
        self._cache_lock = threading.Lock()
        if selected:
            # Download missing grammars now, not in the middle of a parse.
            language_pack.prefetch(list(selected))

    @property
    def languages(self) -> tuple[str, ...]:
        """Configured grammar names, in detection order."""
        return self._languages

    def _parsers(self) -> Iterator[tuple[str, Parser]]:
        cache: dict[str, Parser] | None = getattr(self._local, "parsers", None)
        if cache is None:
            cache = self._local.parsers = {}
        for language in self._languages:
            parser = cache.get(language)
            if parser is None:
                parser = cache[language] = language_pack.get_parser(language)
            yield language, parser

    def detect(self, text: str) -> str | None:
        """Return the first configured language that parses ``text`` as code.

        Args:
            text: One or more lines.

        Returns:
            The language name, or ``None`` when ``text`` is not code in any
            configured language.
        """
        if not text.strip():
            return None
        cacheable = len(text) <= _CACHEABLE_LENGTH
        if cacheable:
            with self._cache_lock:
                if text in self._cache:
                    self._cache.move_to_end(text)
                    return self._cache[text]
        language = self._detect(text)
        if cacheable:
            with self._cache_lock:
                self._cache[text] = language
                self._cache.move_to_end(text)
                if len(self._cache) > _CACHE_SIZE:
                    self._cache.popitem(last=False)
        return language

    def _detect(self, text: str) -> str | None:
        data = (text if text.endswith("\n") else text + "\n").encode("utf-8")
        for language, parser in self._parsers():
            root = parser.parse(data).root_node
            if root.has_error:
                continue
            nodes = [node for node in root.named_children if node.type not in _COMMENTS]
            if (
                nodes
                and all(_is_construct(node, language, text) for node in nodes)
                and not all(_is_plain_assignment(node) for node in nodes)
            ):
                return language
        return None

    def __reduce__(self) -> tuple[type[CodeDetector], tuple[tuple[str, ...]]]:
        # Rebuild through the validating constructor; parsers and the cache
        # are per-process state and are never pickled.
        return (CodeDetector, (self._languages,))
