"""Mixed-content routing across built-in and custom parsers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import override

from parsefabric.aggregation import Aggregator, RoutingAggregator
from parsefabric.builtins.code_detection import DEFAULT_CODE_LANGUAGES, CodeDetector
from parsefabric.builtins.json_parser import JSONParser
from parsefabric.capabilities import ParserCapabilities
from parsefabric.errors import ParseError, ParseIssue
from parsefabric.models import (
    JSONValue,
    ParseContext,
    ParsedEvent,
    ParseResult,
    PatternStatistic,
)
from parsefabric.parser import Parser
from parsefabric.parser._text import iter_text_lines
from parsefabric.patterns import ExactPattern, Pattern, RegexPattern


def _scan_json_brackets(
    line: str, stack: list[str], in_string: bool, escaped: bool
) -> tuple[bool, bool, bool]:
    """Track JSON container boundaries without treating quoted braces as syntax."""
    for character in line:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "{[":
            stack.append("}" if character == "{" else "]")
        elif character in "}]" and (not stack or stack.pop() != character):
            return True, in_string, escaped
    return not stack, in_string, escaped


_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
# Lines that continue the block above them even when they are not indented.
_CONTINUATION = re.compile(r"^\s*(?:else\b|elif\b|except\b|finally\b|catch\b|[}\])])")
_MAX_BLOCK_EXTENSION = 50

_Line = tuple[int, str, int, int]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _blocks(lines: Sequence[_Line]) -> list[list[int]]:
    """Split unmatched lines into indentation blocks (indexes into ``lines``)."""
    blocks: list[list[int]] = []
    base = 0
    for index, (_, line, _, _) in enumerate(lines):
        if blocks and (
            not line.strip()
            or _indent(line) > base
            or _CONTINUATION.match(line)
            or lines[blocks[-1][-1]][1].lstrip().startswith("@")
        ):
            blocks[-1].append(index)
            continue
        blocks.append([index])
        base = _indent(line)
    return blocks


def _covered_lines(events: Iterable[ParsedEvent], lines: Sequence[_Line]) -> set[int]:
    """Line numbers that routed events start on or whose byte spans include.

    Adopted events always carry a line number and a byte span (see ``_adopt``).
    """
    covered: set[int] = set()
    for event in events:
        evidence = event.evidence
        first, last = evidence.start_offset or 0, evidence.end_offset or 0
        covered.add(evidence.line_number or 0)
        covered.update(number for number, _, start, _ in lines if first <= start < last)
    return covered


def _code_languages(detector: CodeDetector, lines: Sequence[_Line]) -> list[str | None]:
    """Return the detected language of each line, ``None`` for non-code lines.

    Code spans lines (``def f():`` alone is not valid), so whole indentation
    blocks are parsed and extended with following blocks while the result stays
    valid (multi-line SQL, decorators); blocks that are not code are retried
    line by line.
    """
    languages: list[str | None] = [None] * len(lines)
    blocks = _blocks(lines)

    def detect(first: int, last: int) -> str | None:
        indexes = [index for block in blocks[first : last + 1] for index in block]
        return detector.detect("\n".join(lines[index][1] for index in indexes))

    position = 0
    while position < len(blocks):
        last = position
        language = detect(position, position)
        if language is None and position + 1 < len(blocks):
            language = detect(position, position + 1)
            last = position + 1
        if language is None:
            if len(blocks[position]) > 1:
                for index in blocks[position]:
                    languages[index] = detector.detect(lines[index][1])
            position += 1
            continue
        while last + 1 < len(blocks) and last - position < _MAX_BLOCK_EXTENSION:
            extended = detect(position, last + 1)
            if extended is None:
                break
            language, last = extended, last + 1
        indexes = [index for block in blocks[position : last + 1] for index in block]
        while indexes and not lines[indexes[-1]][1].strip():
            indexes.pop()
        for index in indexes:
            languages[index] = language
        position = last + 1
    return languages


class MixedContentParser(Parser):
    """Parse documents that mix logs, JSON, code and free text, line by line.

    Each line is classified in this order:

    1. A Markdown code fence (```` ``` ```` or ``~~~``) starts a fenced block.
       Its body is parsed by the parser in ``fence_routes`` for the fence's
       language tag; otherwise, or when that parser rejects the body, every
       body line becomes a ``code`` event. Fence marker lines become
       ``fence`` events.
    2. The first route whose selector matches sends the line to an existing
       parser, whose events are kept with their own parser identity and
       re-based to the line. A JSON route continues over following lines
       until the JSON value is complete.
    3. The first matching pattern, in priority order, produces an event.
    4. Remaining lines are grouped into indentation blocks and become
       ``code`` events (with ``language``) when a tree-sitter grammar parses
       them as code, or ``other`` events with the line as ``text``.

    No line is lost: every line produces at least one event.

    Args:
        patterns: Line patterns. Defaults to one ``log-level`` pattern that
            recognizes ``LEVEL message`` lines, optionally after an ISO date,
            and records ``level``, ``message``, ``text`` and severity.
        routes: ``(selector, parser)`` pairs; routed parsers with the same
            name must be the same instance.
        fence_routes: Parser for each lowercase fence language tag.
        code_languages: Grammars used to detect unfenced code;
            ``()`` disables detection.

    Raises:
        TypeError: If a route is not a ``(Pattern, Parser)`` pair or routes to
            this parser.
        ValueError: If names repeat, a reserved name (``code``,
            ``code_fence``, ``other``) is used, or a fence tag is invalid.
    """

    def __init__(
        self,
        patterns: Sequence[Pattern] | None = None,
        *,
        routes: Sequence[tuple[Pattern, Parser]] = (),
        fence_routes: Mapping[str, Parser] | None = None,
        code_languages: Sequence[str] = DEFAULT_CODE_LANGUAGES,
    ) -> None:
        self._code_detector = (
            CodeDetector(code_languages)
            if isinstance(code_languages, str) or code_languages
            else None
        )
        selected = (
            patterns
            if patterns is not None
            else (
                RegexPattern(
                    "log-level",
                    r"^\s*(?:\d{4}-\d\d-\d\d[ T]\S+\s+)?"
                    r"(?P<level>TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b"
                    r"[:\s]*(?P<message>(?:\S|\s+\S)*)",
                    flags=re.IGNORECASE,
                    priority=20,
                    event_type="log",
                ),
            )
        )
        self._routes = tuple(routes)
        self._fence_routes: dict[str, Parser] = {}
        for language, parser in (fence_routes or {}).items():
            if (
                not isinstance(language, str)
                or not language
                or language != language.strip().lower()
                or any(character.isspace() for character in language)
            ):
                raise ValueError(
                    "fence_routes keys must be lowercase language tags such as 'sql'"
                )
            if not isinstance(parser, Parser):
                raise TypeError("fence_routes values must be Parser instances")
            self._fence_routes[language] = parser
        self._route_parsers: dict[str, Parser] = {}
        route_parsers = self._route_parsers
        for selector, parser in self._routes:
            if not isinstance(selector, Pattern) or not isinstance(parser, Parser):
                raise TypeError("routes must contain (Pattern, Parser) pairs")
            if parser is self:
                raise TypeError(
                    "mixed content routes cannot route to the parser itself"
                )
            if (
                parser.name in route_parsers
                and route_parsers[parser.name] is not parser
            ):
                raise ValueError("routed parsers with the same name must be identical")
            route_parsers[parser.name] = parser
        for parser in self._fence_routes.values():
            if parser is self:
                raise TypeError(
                    "mixed content routes cannot route to the parser itself"
                )
            if (
                parser.name in route_parsers
                and route_parsers[parser.name] is not parser
            ):
                raise ValueError("routed parsers with the same name must be identical")
            route_parsers[parser.name] = parser
        names = [pattern.name for pattern in selected] + [
            selector.name for selector, _ in self._routes
        ]
        if len(names) != len(set(names)) or {"code", "code_fence", "other"} & set(
            names
        ):
            raise ValueError(
                "mixed content pattern names must be unique and reserved names unused"
            )
        self._patterns = tuple(
            sorted(selected, key=lambda pattern: (-pattern.priority, pattern.name))
        )
        self._default_patterns = patterns is None

    @override
    def _build_aggregator(self) -> Aggregator:
        """Fallback events use grouped evidence; routed events use their parser's."""
        return RoutingAggregator(
            super()._build_aggregator(),
            {name: parser.aggregator for name, parser in self._route_parsers.items()},
        )

    @property
    @override
    def name(self) -> str:
        return "mixed-content"

    @property
    @override
    def version(self) -> str:
        return "1"

    @property
    @override
    def capabilities(self) -> ParserCapabilities:
        """Capabilities derived from the patterns, selectors and routed parsers.

        The parser is deterministic and parallel-safe only when every pattern
        and route selector is a `RegexPattern` or
        `ExactPattern` and every routed parser is deterministic and
        parallel-safe, respectively. Mixed content is never partitionable:
        code blocks, fences and multi-line JSON span lines.
        """
        routed = (
            *(parser for _, parser in self._routes),
            *self._fence_routes.values(),
        )
        pure = all(
            isinstance(pattern, (RegexPattern, ExactPattern))
            for pattern in (
                *self._patterns,
                *(selector for selector, _ in self._routes),
            )
        )
        stateful = any(parser.capabilities.stateful for parser in routed)
        requires_order = any(parser.capabilities.requires_order for parser in routed)
        return ParserCapabilities(
            deterministic=pure
            and all(parser.capabilities.deterministic for parser in routed),
            parallel_safe=pure
            and not stateful
            and not requires_order
            and all(parser.capabilities.parallel_safe for parser in routed),
            stateful=stateful,
            requires_order=requires_order,
            aggregatable=True,
        )

    @staticmethod
    def _child_context(context: ParseContext | None, offset: int) -> ParseContext:
        return ParseContext(
            source_id=context.source_id if context else None,
            correlation_id=context.correlation_id if context else None,
            partition_id=context.partition_id if context else None,
            source_offset=offset,
        )

    def _adopt(
        self,
        child: ParseResult,
        route: str,
        line_number: int,
        start: int,
        end: int,
        context: ParseContext | None,
        events: list[ParsedEvent],
        counts: dict[str, int],
    ) -> bool:
        """Re-base a routed parser's events onto the mixed input's lines."""
        for statistic in child.pattern_statistics:
            name = f"{route}:{statistic.pattern_name}"
            counts[name] = counts.get(name, 0) + statistic.matches
        if not child.events:
            return False
        counts[route] = counts.get(route, 0) + 1
        for child_event in child.events:
            evidence = child_event.evidence
            events.append(
                self._with_parser_evidence(
                    child_event.with_evidence(
                        replace(
                            evidence,
                            line_number=(
                                line_number + evidence.line_number - 1
                                if evidence.line_number is not None
                                else line_number
                            ),
                        )
                    ),
                    context,
                    start_offset=(
                        evidence.start_offset
                        if evidence.start_offset is not None
                        else start
                    ),
                    end_offset=(
                        evidence.end_offset if evidence.end_offset is not None else end
                    ),
                    pattern_name=evidence.pattern_name or route,
                )
            )
        return True

    async def _route_fenced_body(
        self,
        language: str,
        data: bytes,
        source_start: int,
        body: list[tuple[int, str, int, int]],
        context: ParseContext | None,
        counts: dict[str, int],
        warnings: list[str],
    ) -> list[ParsedEvent] | None:
        """Parse a fenced body with its language's parser; ``None`` keeps code.

        Only the fence's declared language selects a parser, never the body's
        content. Fenced snippets are often illustrative, so a body the parser
        rejects (a ``ParseError`` or parse issues) stays ``code`` instead of
        failing the document.
        """
        parser = self._fence_routes.get(language)
        if parser is None or not any(line.strip() for _, line, _, _ in body):
            return None
        start, end = body[0][2], body[-1][3]
        routed_text = data[start - source_start : end - source_start]
        try:
            child = await parser.parse(
                routed_text.decode("utf-8"), self._child_context(context, start)
            )
        except ParseError:
            return None
        if child.errors or not child.events:
            return None
        adopted: list[ParsedEvent] = []
        self._adopt(
            child,
            f"code_fence:{language}",
            body[0][0],
            start,
            end,
            context,
            adopted,
            counts,
        )
        warnings.extend(child.warnings)
        return adopted

    @override
    async def parse(
        self,
        source: object,
        context: ParseContext | None = None,
    ) -> ParseResult:
        if isinstance(source, bytes):
            text = source.decode("utf-8", errors="strict")
        elif isinstance(source, str):
            text = source
        else:
            raise TypeError("mixed content parser accepts only str or bytes")

        events: list[ParsedEvent] = []
        warnings: list[str] = []
        errors: list[ParseIssue] = []
        counts = {pattern.name: 0 for pattern in self._patterns}
        counts.update({selector.name: 0 for selector, _ in self._routes})
        counts["code_fence"] = 0
        counts["code"] = 0
        pending: list[_Line] = []
        byte_offset = context.source_offset if context and context.source_offset else 0
        source_start = byte_offset
        source_bytes: bytes | None = None
        lines = iter(enumerate(iter_text_lines(text), start=1))
        line_item = next(lines, None)

        def fallback(
            line: str, kind: str = "other", language: str | None = None
        ) -> ParsedEvent:
            attributes: dict[str, JSONValue] = (
                {} if language is None else {"language": language}
            )
            attributes["text"] = line
            return ParsedEvent(kind, attributes=attributes)

        def append(
            event: ParsedEvent, line_number: int, start: int, end: int, pattern: str
        ) -> None:
            if pattern != "other":
                counts[pattern] += 1
            events.append(
                self._with_parser_evidence(
                    event,
                    context,
                    start_offset=start,
                    end_offset=end,
                    line_number=line_number,
                    pattern_name=pattern,
                )
            )

        def flush() -> None:
            """Emit buffered unmatched lines as detected code or other text."""
            if not pending:
                return
            languages = (
                _code_languages(self._code_detector, pending)
                if self._code_detector is not None
                else [None] * len(pending)
            )
            for (number, line, start, end), language in zip(
                pending, languages, strict=True
            ):
                if language is None:
                    append(fallback(line), number, start, end, "other")
                else:
                    append(fallback(line, "code", language), number, start, end, "code")
            pending.clear()

        while line_item is not None:
            line_number, (line, width) = line_item
            line_item = next(lines, None)
            start = byte_offset
            byte_offset += width
            marker = _FENCE.match(line)
            if marker:
                fence = marker.group(1)
                info = line[marker.end() :].split()
                language = info[0].lower() if info else ""
                flush()
                opening: _Line = (line_number, line, start, byte_offset)
                body: list[tuple[int, str, int, int]] = []
                closing: tuple[int, str, int, int] | None = None
                while line_item is not None:
                    body_number, (body_line, body_width) = line_item
                    line_item = next(lines, None)
                    body_start = byte_offset
                    byte_offset += body_width
                    end_marker = _FENCE.match(body_line)
                    if (
                        end_marker
                        and end_marker.group(1)[0] == fence[0]
                        and len(end_marker.group(1)) >= len(fence)
                        and not body_line[end_marker.end() :].strip()
                    ):
                        closing = (body_number, body_line, body_start, byte_offset)
                        break
                    body.append((body_number, body_line, body_start, byte_offset))
                fence_language = language or (
                    self._code_detector.detect("\n".join(item[1] for item in body))
                    if self._code_detector is not None and body
                    else None
                )
                append(
                    fallback(line, "fence", fence_language),
                    opening[0],
                    opening[2],
                    opening[3],
                    "code_fence",
                )
                if language in self._fence_routes and source_bytes is None:
                    source_bytes = text.encode("utf-8")
                adopted = (
                    await self._route_fenced_body(
                        language,
                        source_bytes or b"",
                        source_start,
                        body,
                        context,
                        counts,
                        warnings,
                    )
                    if body
                    else None
                )
                covered = _covered_lines(adopted or (), body)
                by_line: dict[int, list[ParsedEvent]] = {}
                for routed_event in adopted or ():
                    by_line.setdefault(
                        routed_event.evidence.line_number or 0, []
                    ).append(routed_event)
                for body_number, body_line, body_start, body_end in body:
                    events.extend(by_line.pop(body_number, ()))
                    if body_number not in covered:
                        append(
                            fallback(body_line, "code", fence_language),
                            body_number,
                            body_start,
                            body_end,
                            "code_fence",
                        )
                if closing is not None:
                    closing_number, closing_line, closing_start, closing_end = closing
                    append(
                        fallback(closing_line, "fence", fence_language),
                        closing_number,
                        closing_start,
                        closing_end,
                        "code_fence",
                    )
                continue
            routed = False
            for selector, parser in self._routes:
                if selector.match(line) is None:
                    continue
                routed_text = line
                if isinstance(parser, JSONParser) and line.lstrip().startswith(
                    ("{", "[")
                ):
                    stack: list[str] = []
                    complete, in_string, escaped = _scan_json_brackets(
                        line, stack, False, False
                    )
                    if not complete:
                        if source_bytes is None:
                            source_bytes = text.encode("utf-8")
                        while line_item is not None:
                            _, (next_line, next_width) = line_item
                            if (
                                _FENCE.match(next_line)
                                or any(
                                    not isinstance(child_parser, JSONParser)
                                    and next_selector.match(next_line) is not None
                                    for next_selector, child_parser in self._routes
                                )
                                or any(
                                    pattern.match(next_line) is not None
                                    for pattern in self._patterns
                                )
                            ):
                                break
                            byte_offset += next_width
                            complete, in_string, escaped = _scan_json_brackets(
                                next_line, stack, in_string, escaped
                            )
                            line_item = next(lines, None)
                            if complete:
                                break
                        routed_text = source_bytes[
                            start - source_start : byte_offset - source_start
                        ].decode("utf-8")
                flush()
                child = await parser.parse(
                    routed_text, self._child_context(context, start)
                )
                warnings.extend(child.warnings)
                errors.extend(child.errors)
                if self._adopt(
                    child,
                    selector.name,
                    line_number,
                    start,
                    byte_offset,
                    context,
                    events,
                    counts,
                ):
                    routed = True
                    break
            if routed:
                continue
            matched = next(
                (
                    (pattern, match)
                    for pattern in self._patterns
                    if (match := pattern.match(line)) is not None
                ),
                None,
            )
            if matched is None:
                pending.append((line_number, line, start, byte_offset))
                continue
            flush()
            pattern, match = matched
            event = pattern.to_event(match)
            if self._default_patterns:
                attributes = dict(event.attributes)
                level = attributes.get("level")
                attributes["text"] = line
                event = replace(
                    event,
                    attributes=attributes,
                    severity=level.upper() if isinstance(level, str) else None,
                )
            append(event, line_number, start, byte_offset, pattern.name)
        flush()
        return ParseResult(
            events=tuple(events),
            warnings=tuple(warnings),
            errors=tuple(errors),
            pattern_statistics=tuple(
                PatternStatistic(name, count) for name, count in sorted(counts.items())
            ),
            parser_name=self.name,
            parser_version=self.version,
            correlation_id=context.correlation_id if context else None,
        )
