"""Query-time expansion from authorized managed abbreviation entries."""

from __future__ import annotations

import re

from rag.abbreviations.models import AbbreviationEntryRecord
from rag.abbreviations.service import AbbreviationGlossaryService
from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE

from .qdrant import SearchHit
from .state import QueryContext, active_query


_QUERY_ABBREVIATION_RE = re.compile(
    r"(?<!\w)([A-Z][A-Z0-9]*(?:[./&-][A-Z0-9]+)*)(?!\w)",
    re.IGNORECASE,
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
    entries_by_abbreviation: dict[str, list[AbbreviationEntryRecord]] = {}
    for entry in entries:
        entries_by_abbreviation.setdefault(entry.abbreviation.casefold(), []).append(
            entry
        )
    direct_matches: dict[
        str, list[tuple[int, int, str, AbbreviationEntryRecord]]
    ] = {}
    direct_support_ids: dict[tuple[int, int, str, str], set[str]] = {}
    for alternatives in entries_by_abbreviation.values():
        entry = alternatives[0]
        expansions = list(dict.fromkeys(item.expansion for item in alternatives))
        for match in _expansion_pattern(entry.abbreviation).finditer(query):
            replacement = f"{match[0]} ({' OR '.join(expansions)})"
            candidate = (match.start(), match.end(), replacement, entry)
            direct_matches.setdefault(entry.id, []).append(candidate)
            direct_support_ids[
                (match.start(), match.end(), replacement, entry.id)
            ] = {item.id for item in alternatives}

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

    paired_ids = {
        entry_id
        for entry_id, matches in direct_matches.items()
        if any(
            direct_support_ids[(start, end, replacement, entry.id)]
            & reverse_matches.keys()
            for start, end, replacement, entry in matches
        )
    }
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
    matched_ids = set(paired_ids)
    for start, end, replacement, entry in selected:
        matched_ids.update(
            direct_support_ids.get((start, end, replacement, entry.id), {entry.id})
        )
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
            "provenance_kind": "structured",
            "quote_texts": [f"{entry.abbreviation} — {entry.expansion}"],
            "citation_targets": [{"kind": "record", "record_id": entry.id,
                "exact_text": f"{entry.abbreviation} — {entry.expansion}", "provenance_kind": "structured"}],
        },
    )


def _query_abbreviations(query: str) -> list[str]:
    matches = list(_QUERY_ABBREVIATION_RE.finditer(query))
    candidates: list[str] = []
    for start, first in enumerate(matches):
        candidate = first[1]
        if 2 <= len(re.sub(r"\W", "", candidate)) <= 20:
            candidates.append(candidate)
        for end in range(start + 1, len(matches)):
            previous = matches[end - 1]
            current = matches[end]
            if not query[previous.end() : current.start()].isspace():
                break
            candidate = f"{candidate} {current[1]}"
            if len(candidate) > 20:
                break
            candidates.append(candidate)
    return list(dict.fromkeys(candidates))
