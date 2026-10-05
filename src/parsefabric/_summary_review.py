"""Structured summary claims and deterministic evidence checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parsefabric.aggregation.evidence import EvidenceAggregate


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    context_ids: list[str] = Field(default_factory=list)
    occurrences: int = Field(ge=1)


class Claims(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claims: list[Claim]


class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    issues: list[str]


@dataclass(frozen=True)
class Fact:
    id: str
    source_id: str | None
    event_type: str
    severity: str | None
    message: object
    occurrences: int
    positions: tuple[int | None, ...]
    timestamps: tuple[tuple[int | None, str], ...]
    timestamps_known: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "event_type": self.event_type,
            "severity": self.severity,
            "message": self.message,
            "occurrences": self.occurrences,
            "positions": self.positions,
            "timestamps": self.timestamps,
            "timestamps_known": self.timestamps_known,
        }


def facts_for(aggregates: tuple[EvidenceAggregate, ...]) -> tuple[Fact, ...]:
    """Merge disjoint runs of an identical finding without re-counting text."""
    grouped: dict[str, list[Fact]] = {}
    for aggregate in aggregates:
        for group in aggregate.groups:
            for entry in group.evidence:
                key = json.dumps(
                    [
                        aggregate.source_id,
                        aggregate.parser_name,
                        aggregate.parser_version,
                        aggregate.event_type,
                        group.pattern,
                        group.severity,
                        entry.message,
                    ],
                    sort_keys=True,
                )
                grouped.setdefault(key, []).append(
                    Fact(
                        "",
                        aggregate.source_id,
                        aggregate.event_type,
                        group.severity,
                        entry.message,
                        entry.occurrences,
                        entry.positions,
                        tuple(
                            (event.evidence.line_number, event.timestamp.isoformat())
                            for event in entry.events
                            if event.timestamp is not None
                        ),
                        bool(entry.events),
                    )
                )
    facts: list[Fact] = []
    for index, runs in enumerate(grouped.values()):
        first = runs[0]
        positions = tuple(
            sorted(
                (position for run in runs for position in run.positions),
                key=lambda position: position if position is not None else float("inf"),
            )
        )
        facts.append(
            Fact(
                f"e{index}",
                first.source_id,
                first.event_type,
                first.severity,
                first.message,
                sum(run.occurrences for run in runs),
                positions,
                tuple(
                    sorted(
                        (timestamp for run in runs for timestamp in run.timestamps),
                        key=lambda item: (
                            item[0] if item[0] is not None else float("inf"),
                            item[1],
                        ),
                    )
                ),
                all(run.timestamps_known for run in runs),
            )
        )
    return tuple(facts)


_CLOCK = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_CITATION = re.compile(r"\[(?:L?\d|lines?\b)", re.IGNORECASE)
_TIME_ASSERTION = re.compile(r"\b(?:untimestamped|timestamped)\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\w)[+-]?\d+(?:\.\d+)?(?!\w)")


def check_claims(text: str, facts: tuple[Fact, ...]) -> tuple[Claims, list[str]]:
    """Check drafted claims against the facts deterministically.

    Returns the parsed claims (empty when the draft is not valid JSON for the
    schema) and the issues that must be repaired before critique.
    """
    try:
        claims = Claims.model_validate_json(text)
    except ValidationError:
        return Claims(claims=[]), [
            "Return valid JSON matching the supplied Claims schema."
        ]
    by_id = {fact.id: fact for fact in facts}
    used: set[str] = set()
    issues: list[str] = []
    for number, claim in enumerate(claims.claims, 1):
        ids = set(claim.evidence_ids)
        context_ids = set(claim.context_ids)
        if len(ids) != len(claim.evidence_ids):
            issues.append(f"Claim {number}: duplicate evidence IDs.")
        if not ids <= by_id.keys():
            issues.append(f"Claim {number}: unknown evidence IDs.")
            continue
        if not context_ids <= by_id.keys():
            issues.append(f"Claim {number}: unknown context IDs.")
            continue
        if len(context_ids) != len(claim.context_ids) or ids & context_ids:
            issues.append(f"Claim {number}: duplicate context references.")
        if ids & used:
            issues.append(f"Claim {number}: evidence counted in more than one claim.")
        used.update(ids)
        selected = [by_id[id_] for id_ in claim.evidence_ids]
        support = [*selected, *(by_id[id_] for id_ in claim.context_ids)]
        if any(fact.event_type == "fence" for fact in support):
            issues.append(f"Claim {number}: fence delimiters cannot support claims.")
        if claim.occurrences != sum(fact.occurrences for fact in selected):
            issues.append(f"Claim {number}: occurrences do not match cited evidence.")
        if not claim.text.strip():
            issues.append(f"Claim {number}: text must not be blank.")
        if (
            _CLOCK.search(claim.text)
            or _CITATION.search(claim.text)
            or _TIME_ASSERTION.search(claim.text)
        ):
            issues.append(
                f"Claim {number}: timestamps and citations belong to the renderer, "
                "not claim text."
            )
        supplied_numbers = {
            value
            for fact in support
            for value in _NUMBER.findall(json.dumps(fact.message))
        }
        if set(_NUMBER.findall(claim.text)) - supplied_numbers:
            issues.append(
                f"Claim {number}: numeric values are absent from cited evidence."
            )
    required = {
        fact.id
        for fact in facts
        if (fact.severity or "").upper()
        in {"ERROR", "WARN", "WARNING", "CRITICAL", "FATAL"}
        and fact.event_type != "fence"
    }
    if required - used:
        issues.append("Include every error/warning finding with its exact total.")
    return claims, issues


def render_claims(
    documents: list[tuple[Claims, tuple[Fact, ...]]],
) -> str:
    """Render checked counts and exact positions without another model call."""
    rows: list[tuple[str, int, str]] = []
    occurrences: list[tuple[str, int, int, str]] = []
    for document, facts in documents:
        by_id = {fact.id: fact for fact in facts}
        selected_ids = {id_ for claim in document.claims for id_ in claim.evidence_ids}
        complete = [
            *document.claims,
            *(
                Claim(
                    text="Source record.",
                    evidence_ids=[fact.id],
                    occurrences=fact.occurrences,
                )
                for fact in facts
                if fact.id not in selected_ids and fact.event_type != "fence"
            ),
        ]
        for claim in complete:
            selected = [by_id[id_] for id_ in claim.evidence_ids]
            context = [by_id[id_] for id_ in claim.context_ids]
            citations: list[str] = []
            timestamps: list[str] = []
            for fact in selected:
                message = json.dumps(fact.message, ensure_ascii=False, allow_nan=False)
                timestamps_by_position: dict[int | None, list[str]] = {}
                for position, timestamp in fact.timestamps:
                    timestamps_by_position.setdefault(position, []).append(timestamp)
                positions = ", ".join(
                    str(position) if position is not None else "unknown"
                    for position in fact.positions
                )
                source = json.dumps(fact.source_id, ensure_ascii=False)
                citations.append(f"source {source}, lines {positions}")
                timestamps.extend(
                    f"line {position}: {value}" for position, value in fact.timestamps
                )
                for position in fact.positions:
                    if position is None:
                        continue
                    occurrence = (
                        f"- [source {source}, line {position}] Recorded evidence: "
                        f"{message}."
                    )
                    recorded = timestamps_by_position.get(position, [])
                    if recorded:
                        occurrence += (
                            " Recorded timestamps: " + "; ".join(recorded) + "."
                        )
                    occurrences.append(
                        (fact.source_id or "", position, len(rows), occurrence)
                    )
            count_label = (
                ("occurrence" if claim.occurrences == 1 else "occurrences")
                if len(selected) == 1
                else "supporting records"
            )
            row = (
                f"- {claim.text.strip()} **{claim.occurrences} "
                f"{count_label} total** "
                f"[{'; '.join(citations)}]."
            )
            messages = [
                json.dumps(fact.message, ensure_ascii=False, allow_nan=False)
                for fact in selected
            ]
            row += " Recorded evidence: " + "; ".join(messages) + "."
            if context:
                context_messages = [
                    f"source {json.dumps(fact.source_id, ensure_ascii=False)}, lines "
                    + ", ".join(
                        str(position) if position is not None else "unknown"
                        for position in fact.positions
                    )
                    + ": "
                    + json.dumps(fact.message, ensure_ascii=False, allow_nan=False)
                    for fact in context
                ]
                row += (
                    " Context evidence (not additional occurrences): "
                    + "; ".join(context_messages)
                    + "."
                )
            if timestamps:
                row += " Recorded timestamps: " + "; ".join(timestamps) + "."
            first = min(
                (
                    position
                    for fact in selected
                    for position in fact.positions
                    if position is not None
                ),
                default=0,
            )
            rows.append((selected[0].source_id or "", first, row))
    text = "\n".join(row for _, _, row in sorted(rows, key=lambda row: row[:2]))
    ordered = sorted(occurrences, key=lambda item: item[:2])
    visited: set[int] = set()
    previous: int | None = None
    interleaved = False
    for _, _, owner, _ in ordered:
        if owner != previous and owner in visited:
            interleaved = True
        visited.add(owner)
        previous = owner
    if interleaved:
        text += "\n\n### Source-order occurrence timeline\n"
        text += "\n".join(row for _, _, _, row in ordered)
    return text
