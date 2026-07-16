"""Fail-closed document-section scope rules for exhaustive reranking."""

from __future__ import annotations

import re
from typing import Any

from rag.query.retrieval.metadata_scoring import low_value_chunk_penalty
from ..qdrant import SearchHit
from .models import ExhaustiveUnit
from .text import hit_identity, match_tokens, normalized_text, searchable_text, tokens

_EXHAUSTIVE_CATEGORY_CONTROL_TOKENS = {
    "all",
    "and",
    "any",
    "complete",
    "comprehensive",
    "do",
    "dont",
    "document",
    "documents",
    "each",
    "every",
    "file",
    "files",
    "find",
    "give",
    "include",
    "including",
    "list",
    "manual",
    "manuals",
    "mis",
    "miss",
    "need",
    "needed",
    "not",
    "pdf",
    "pdfs",
    "please",
    "provide",
    "repair",
    "repairs",
    "require",
    "required",
    "requires",
    "show",
    "skip",
    "source",
    "sources",
    "tell",
    "want",
}
_EQUIPMENT_CATEGORY_TOKENS = {
    "apparatus",
    "equipment",
    "gear",
    "instrument",
    "tool",
}
_BROADENING_SECTION_SCOPE_PHRASES = {
    "across the document",
    "across the manual",
    "as well as",
    "beyond",
    "in addition to",
    "including but not limited to",
    "not from",
    "not just",
    "not only",
    "other than",
    "outside of",
}


def is_toc_only_exhaustive_unit(query: str, unit: ExhaustiveUnit) -> bool:
    return bool(unit.children) and all(
        is_toc_exhaustive_hit(query, child) for child in unit.children
    )


def is_toc_exhaustive_hit(query: str, hit: SearchHit) -> bool:
    if "toc_or_index" not in low_value_chunk_penalty(query, hit)[1]:
        return False
    return _has_proven_toc_marker(hit.payload)


def _has_proven_toc_marker(payload: dict[str, Any]) -> bool:
    if payload.get("is_toc") is True:
        return True
    quality_flags = payload.get("quality_flags")
    if isinstance(quality_flags, list):
        normalized_flags = {normalized_text(flag) for flag in quality_flags}
        if normalized_flags & {"contents", "index", "table of contents", "toc"}:
            return True
    chunk_type = normalized_text(payload.get("chunk_type"))
    if chunk_type in {"index", "table of contents", "toc"}:
        return True
    heading_values: list[object] = [payload.get("section_title")]
    section_path = payload.get("section_path")
    if isinstance(section_path, list):
        heading_values.extend(section_path)
    if any(normalized_text(value) == "table of contents" for value in heading_values):
        return True
    text = str(payload.get("text") or "")
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return normalized_text(first_line) == "table of contents"


def referenced_exhaustive_unit_keys(
    query: str,
    hits: list[SearchHit],
    units: list[ExhaustiveUnit],
    *,
    head_limit: int,
) -> tuple[set[str], set[str], set[str]]:
    query_text = normalized_text(query)
    unit_key_by_hit = {
        hit_identity(child): unit.key for unit in units for child in unit.children
    }
    head = [
        hit
        for hit in hits[: max(1, head_limit)]
        if "toc_or_index" not in low_value_chunk_penalty(query, hit)[1]
    ]
    normalized_head_text = [normalized_text(searchable_text(hit)) for hit in head]
    query_referenced: set[str] = set()
    for unit in units:
        phrases = _unit_heading_phrases(unit)
        if not phrases:
            continue
        if any(contains_normalized_phrase(query_text, phrase) for phrase in phrases):
            query_referenced.add(unit.key)
    referenced = set(query_referenced)
    for unit in units:
        phrases = _unit_heading_phrases(unit)
        if not phrases or unit.key in query_referenced:
            continue
        for hit, text in zip(head, normalized_head_text, strict=True):
            if unit_key_by_hit.get(hit_identity(hit)) == unit.key:
                continue
            if any(contains_normalized_phrase(text, phrase) for phrase in phrases):
                referenced.add(unit.key)
                break
    exclusive_scope = _exclusive_query_section_unit_keys(query_text, units)
    return referenced, query_referenced, exclusive_scope


def _exclusive_query_section_unit_keys(
    query_text: str,
    units: list[ExhaustiveUnit],
) -> set[str]:
    if (
        any(phrase in query_text for phrase in _BROADENING_SECTION_SCOPE_PHRASES)
        or requires_full_section_coverage(query_text)
        or requires_document_summary_coverage(query_text)
    ):
        return set()
    mentions = _query_heading_mentions(query_text, units)
    if not mentions:
        return set()

    if len(mentions) == 1:
        start, end, unit_keys = mentions[0]
        if _is_direct_heading_scope(query_text, query_text[start:end]):
            return set(unit_keys)

    first_start = mentions[0][0]
    scope_match = re.search(
        r"(?<!\w)(?:from|in|inside|under|within)\s+"
        r"(?:the\s+)?(?:section\s+)?$",
        query_text[:first_start],
    )
    if scope_match is None or not _is_positive_scope_lead(
        query_text[: scope_match.start()]
    ):
        return set()
    for previous, current in zip(mentions, mentions[1:], strict=False):
        if not _is_positive_scope_bridge(query_text[previous[1] : current[0]]):
            return set()
    if not _is_safe_positive_scope_suffix(query_text[mentions[-1][1] :]):
        return set()
    return {key for _start, _end, keys in mentions for key in keys}


def _query_heading_mentions(
    query_text: str,
    units: list[ExhaustiveUnit],
) -> list[tuple[int, int, frozenset[str]]] | None:
    keys_by_span: dict[tuple[int, int], set[str]] = {}
    for unit in units:
        for phrase in _unit_heading_phrases(unit):
            for match in re.finditer(
                rf"(?<!\w){re.escape(phrase)}(?!\w)",
                query_text,
            ):
                keys_by_span.setdefault(match.span(), set()).add(unit.key)

    non_overlapping: list[tuple[int, int, frozenset[str]]] = []
    for (start, end), unit_keys in sorted(
        keys_by_span.items(),
        key=lambda item: (item[0][0], -(item[0][1] - item[0][0])),
    ):
        if non_overlapping and start < non_overlapping[-1][1]:
            return None
        non_overlapping.append((start, end, frozenset(unit_keys)))
    return non_overlapping


def _is_positive_scope_lead(lead: str) -> bool:
    normalized = normalized_text(lead)
    if not normalized or has_inverse_scope_language(normalized):
        return False
    polite = r"(?:(?:please|kindly)\s+)?"
    modal = r"(?:(?:can|could|would)\s+you(?:\s+please)?\s+)?"
    verb = r"(?:display|enumerate|extract|find|get|give|identify|list|provide|return|show|tell)"
    head = (
        r"(?:content|contents|data|details?|documents?|entries|entry|equipment|equipments|"
        r"evidence|facts?|files?|information|items?|records?|sections?|sources?|table|tools?)"
    )
    qualified_head = (
        rf"(?:(?:all|any|each|every)\s+)?(?:(?:a|an|the)\s+)?"
        rf"(?:(?:available|complete|listed|matching|relevant|required|repair)\s+)*{head}"
    )
    object_phrase = rf"(?:(?:a|the)\s+list\s+of\s+{qualified_head}|{qualified_head})"
    verb_request = rf"{polite}{modal}{verb}\s+(?:me\s+)?(?:about\s+)?{object_phrase}"
    personal_request = rf"{polite}i\s+(?:need|want)\s+{object_phrase}"
    return (
        re.fullmatch(rf"(?:{verb_request}|{personal_request})", normalized) is not None
    )


def _is_positive_scope_bridge(gap: str) -> bool:
    return (
        re.fullmatch(
            r"\s*(?:and|or)\s+"
            r"(?:(?:from|in|inside|under|within)\s+)?"
            r"(?:the\s+)?(?:section\s+)?",
            gap,
        )
        is not None
    )


def _is_safe_positive_scope_suffix(suffix: str) -> bool:
    normalized = normalized_text(suffix)
    if normalized in {
        "",
        "only",
        "only please",
        "please",
        "section",
        "section only",
        "section only please",
        "section please",
    }:
        return True
    return (
        re.fullmatch(
            r"(?:section\s+)?(?:only\s+)?(?:and\s+)?"
            r"(?:do not|don t|dont|never)\s+"
            r"(?:miss|omit|skip)(?:\s+or\s+(?:miss|omit|skip))*"
            r"(?:\s+(?:any|anything|content|details?|entries?|evidence|information|items?))*"
            r"(?:\s+please)?",
            normalized,
        )
        is not None
    )


def has_inverse_scope_language(text: str) -> bool:
    normalized = normalized_text(text)
    normalized = re.sub(
        r"\b(?:do not|don t|dont|never)\s+(?:miss|omit|skip)\b",
        " ",
        normalized,
    )
    if re.search(r"\b(?:[a-z]+n t|dont|rather than|instead of)\b", normalized):
        return True
    inverse_tokens = {
        "apart",
        "aside",
        "avoid",
        "avoiding",
        "different",
        "discard",
        "discarding",
        "drop",
        "dropping",
        "except",
        "exclude",
        "excluded",
        "excluding",
        "ignore",
        "ignoring",
        "leave",
        "no",
        "not",
        "omit",
        "omitting",
        "other",
        "outside",
        "remove",
        "removing",
        "skip",
        "skipping",
        "without",
    }
    return bool(inverse_tokens & set(normalized.split()))


def _is_direct_heading_scope(query_text: str, phrase: str) -> bool:
    polite_prefixes = (
        "can you please ",
        "could you please ",
        "would you please ",
        "can you ",
        "could you ",
        "would you ",
        "kindly ",
        "please ",
    )
    for prefix in polite_prefixes:
        if query_text.startswith(prefix):
            query_text = query_text[len(prefix) :]
            break
    for suffix in (" kindly", " please"):
        if query_text.endswith(suffix):
            query_text = query_text[: -len(suffix)]
            break

    direct_forms = {phrase, f"the {phrase}"}
    for command in ("display", "open", "show"):
        direct_forms.update(
            {
                f"{command} {phrase}",
                f"{command} the {phrase}",
                f"{command} me {phrase}",
                f"{command} me the {phrase}",
            }
        )
    return query_text in direct_forms


def contains_normalized_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _unit_heading_phrases(unit: ExhaustiveUnit) -> tuple[str, ...]:
    first = unit.children[0]
    raw_phrases: list[str] = []
    section_title = first.payload.get("section_title")
    if isinstance(section_title, str):
        raw_phrases.append(section_title)
    section_path = first.payload.get("section_path")
    if isinstance(section_path, list):
        raw_phrases.extend(item for item in section_path if isinstance(item, str))
    phrases: list[str] = []
    for value in raw_phrases:
        phrase = normalized_text(value)
        if len(tokens(phrase)) < 2 or len(phrase) < 8:
            continue
        if phrase not in phrases:
            phrases.append(phrase)
    return tuple(phrases)


def heading_matched_exhaustive_unit_keys(
    query: str,
    units: list[ExhaustiveUnit],
) -> set[str]:
    query_tokens = {
        _canonical_category_token(token)
        for token in match_tokens(query)
        if token not in _EXHAUSTIVE_CATEGORY_CONTROL_TOKENS
    }
    if not query_tokens:
        return set()

    unit_tokens = {unit.key: _unit_heading_match_tokens(unit) for unit in units}
    return {unit.key for unit in units if unit_tokens[unit.key] & query_tokens}


def _unit_heading_match_tokens(unit: ExhaustiveUnit) -> set[str]:
    first = unit.children[0]
    values: list[str] = []
    for field in ("section_title", "table_title", "table_caption"):
        value = first.payload.get(field)
        if isinstance(value, str) and value.strip():
            values.append(value)
    section_path = first.payload.get("section_path")
    if isinstance(section_path, list):
        for value in reversed(section_path):
            if isinstance(value, str) and value.strip():
                values.append(value)
                break
    return {
        _canonical_category_token(token)
        for value in values
        for token in match_tokens(value)
    }


def _canonical_category_token(token: str) -> str:
    return "equipment" if token in _EQUIPMENT_CATEGORY_TOKENS else token


def requires_full_section_coverage(query: str) -> bool:
    normalized = normalized_text(query)
    if has_inverse_scope_language(normalized):
        return False
    if "everything" in tokens(normalized):
        return True
    return any(
        phrase in normalized
        for phrase in (
            "all sections",
            "across the document",
            "across the file",
            "across the manual",
            "across the source",
            "each section",
            "every section",
            "entire document",
            "entire file",
            "entire manual",
            "entire source",
            "everything in every document",
            "throughout document",
            "throughout file",
            "throughout manual",
            "throughout source",
            "throughout the document",
            "throughout the file",
            "throughout the manual",
            "throughout the source",
            "whole document",
            "whole file",
            "whole manual",
            "whole source",
        )
    )


def requires_document_summary_coverage(query: str) -> bool:
    normalized = normalized_text(query)
    if has_inverse_scope_language(normalized):
        return False
    query_tokens = tokens(normalized)
    return bool(
        {"summary", "summaries", "summarize"} & query_tokens
        and {"document", "documents", "file", "files", "source", "sources"}
        & query_tokens
    )
