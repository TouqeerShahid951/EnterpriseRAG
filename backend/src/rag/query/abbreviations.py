"""Query-time expansion from authorized managed abbreviation entries."""

from __future__ import annotations

import re

from rag.abbreviations.models import AbbreviationEntryRecord
from rag.abbreviations.service import AbbreviationGlossaryService
from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE

from .qdrant import SearchHit
from .state import QueryContext, active_query


_QUERY_ABBREVIATION_RE = re.compile(
    r"(?<!\w)([A-Z][A-Z0-9]*(?:[./&-][A-Z0-9]+)*)(?!\w)"
)


def resolve_abbreviation_query(
    ctx: QueryContext,
    *,
    service: AbbreviationGlossaryService,
) -> tuple[str, list[SearchHit], bool]:
    query = active_query(ctx)
    abbreviations = _query_abbreviations(query)
    entries = service.query_entries(abbreviations, query=query)
    return _apply_aliases(query, entries)


def _apply_aliases(
    query: str,
    entries: list[AbbreviationEntryRecord],
) -> tuple[str, list[SearchHit], bool]:
    entries_by_abbreviation = {entry.abbreviation: entry for entry in entries}
    direct_matches: dict[
        str, list[tuple[int, int, str, AbbreviationEntryRecord]]
    ] = {}
    for match in _QUERY_ABBREVIATION_RE.finditer(query):
        entry = entries_by_abbreviation.get(match[1])
        if entry is not None:
            direct_matches.setdefault(entry.id, []).append(
                (
                    match.start(),
                    match.end(),
                    f"{match[1]} ({entry.expansion})",
                    entry,
                )
            )

    entries_by_expansion: dict[str, list[AbbreviationEntryRecord]] = {}
    reverse_matches: dict[
        str, list[tuple[int, int, str, AbbreviationEntryRecord]]
    ] = {}
    for entry in entries:
        entries_by_expansion.setdefault(_normalized_expansion(entry.expansion), []).append(
            entry
        )
        for match in _expansion_pattern(entry.expansion).finditer(query):
            reverse_matches.setdefault(entry.id, []).append(
                (
                    match.start(),
                    match.end(),
                    f"{match[0]} ({entry.abbreviation})",
                    entry,
                )
            )

    paired_ids = direct_matches.keys() & reverse_matches.keys()
    candidates = [
        match
        for entry_id, matches in direct_matches.items()
        if entry_id not in paired_ids
        for match in matches
    ]
    candidates.extend(
        match
        for expansion_entries in entries_by_expansion.values()
        if len(expansion_entries) == 1
        for match in reverse_matches.get(expansion_entries[0].id, [])
        if expansion_entries[0].id not in paired_ids
    )
    selected = _select_non_overlapping(candidates)
    matched_ids = set(paired_ids) | {match[3].id for match in selected}
    if not matched_ids:
        return query, [], False

    resolved = query
    for start, end, replacement, _entry in sorted(
        selected, key=lambda match: match[0], reverse=True
    ):
        resolved = f"{resolved[:start]}{replacement}{resolved[end:]}"
    supporting_hits = [
        _supporting_hit(entry) for entry in entries if entry.id in matched_ids
    ]
    return resolved, supporting_hits, True


def _select_non_overlapping(
    matches: list[tuple[int, int, str, AbbreviationEntryRecord]],
) -> list[tuple[int, int, str, AbbreviationEntryRecord]]:
    selected: list[tuple[int, int, str, AbbreviationEntryRecord]] = []
    for candidate in sorted(
        matches, key=lambda match: (-(match[1] - match[0]), match[0])
    ):
        if all(
            candidate[1] <= current[0] or candidate[0] >= current[1]
            for current in selected
        ):
            selected.append(candidate)
    return selected


def _expansion_pattern(expansion: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(part) for part in expansion.split())
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def _normalized_expansion(expansion: str) -> str:
    return " ".join(expansion.casefold().split())


def _supporting_hit(entry: AbbreviationEntryRecord) -> SearchHit:
    title = entry.source_document_title or "Managed Abbreviation Glossary"
    document_id = entry.source_document_id or "managed-glossary:global"
    return SearchHit(
        point_id=f"abbreviation:{entry.id}",
        score=1.0,
        payload={
            "doc_id": document_id,
            "doc_title": title,
            "chunk_id": f"abbreviation:{entry.id}",
            "doc_type": ABBREVIATION_GLOSSARY_DOC_TYPE,
            "text": f"{entry.abbreviation} — {entry.expansion}",
            "structured_kind": "table_row",
            "structured_fields": [
                {"label": "Abbreviation", "value": entry.abbreviation},
                {"label": "Definition", "value": entry.expansion},
            ],
            "clearance_level": "NATO_UNCLASSIFIED",
            "is_current": True,
            "page": entry.source_page,
            "page_start": entry.source_page,
            "page_end": entry.source_page,
            "abbreviation_glossary_support": True,
        },
    )


def _query_abbreviations(query: str) -> list[str]:
    return list(
        dict.fromkeys(
            match[1]
            for match in _QUERY_ABBREVIATION_RE.finditer(query)
            if 2 <= len(re.sub(r"\W", "", match[1])) <= 20
        )
    )
