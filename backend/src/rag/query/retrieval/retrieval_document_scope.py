"""Document-scope inference and fair cross-document ordering."""

from __future__ import annotations

import re

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from rag.query.qdrant import SearchHit
from rag.query.retrieval.retrieval_hits import _doc_ids, _hit_doc_id, _hit_focus_tokens, _optional_int
from rag.query.routing.routing_models import RoutePlan

_STRUCTURED_QUERY_STOPWORDS = {
    "all",
    "give",
    "list",
    "me",
    "number",
    "numbers",
    "of",
    "show",
    "the",
}
_EXHAUSTIVE_SCOPE_TOKENS = {
    "all",
    "complete",
    "each",
    "entire",
    "every",
    "full",
    "inventory",
    "list",
    "summaries",
    "summary",
    "summarize",
}
_DOCUMENT_SCOPE_STOPWORDS = _STRUCTURED_QUERY_STOPWORDS | {
    "a",
    "about",
    "across",
    "among",
    "an",
    "and",
    "any",
    "as",
    "brief",
    "by",
    "can",
    "commited",
    "committed",
    "could",
    "detail",
    "details",
    "do",
    "does",
    "done",
    "each",
    "entire",
    "every",
    "for",
    "from",
    "full",
    "in",
    "include",
    "including",
    "inside",
    "into",
    "on",
    "or",
    "over",
    "please",
    "provide",
    "summaries",
    "summarize",
    "summary",
    "tell",
    "that",
    "these",
    "this",
    "through",
    "to",
    "within",
    "with",
    "would",
    "you",
}
_BROAD_DOCUMENT_SCOPE_TOKENS = {
    "doc",
    "docs",
    "document",
    "documents",
    "file",
    "files",
    "source",
    "sources",
}
_DOCUMENT_SCOPE_FOCUS_STOPWORDS = (
    _DOCUMENT_SCOPE_STOPWORDS
    | _BROAD_DOCUMENT_SCOPE_TOKENS
    | {
        "activity",
        "activities",
        "are",
        "be",
        "been",
        "being",
        "did",
        "doing",
        "is",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
)
_DOCUMENT_SCOPE_FIELDS = (
    "doc_title",
    "source_id",
    "generated_doc_type",
    "doc_type",
    "auto_doc_type",
    "file_name",
    "filename",
    "mime_type",
)
_DOCUMENT_KIND_TOKENS = {
    "contract",
    "doc",
    "document",
    "file",
    "fir",
    "guide",
    "handbook",
    "invoice",
    "manual",
    "pdf",
    "policy",
    "report",
    "source",
}
_GENERIC_SUBJECT_TOKENS = {
    "component",
    "device",
    "equipment",
    "item",
    "machine",
    "necessary",
    "needed",
    "part",
    "product",
    "required",
    "system",
    "tool",
    "unit",
}
_GENERIC_SCOPE_TOKENS = _DOCUMENT_KIND_TOKENS | _GENERIC_SUBJECT_TOKENS
_DOCUMENT_TARGET_ACTIONS = (
    "diagnose",
    "fix",
    "install",
    "maintain",
    "repair",
    "replace",
    "service",
    "troubleshoot",
)
_DOCUMENT_TARGET_NOUNS = (
    "device",
    "equipment",
    "machine",
    "phone",
    "product",
    "screen",
    "system",
    "tablet",
    "unit",
)
_DOCUMENT_SELECTOR_SUFFIX_TOKENS = {
    "chapter",
    "edition",
    "page",
    "part",
    "section",
    "version",
    "volume",
}
_DOCUMENT_TARGET_TRAILING_ADJUNCTS = (
    "about",
    "across",
    "according to",
    "after",
    "among",
    "as",
    "based on",
    "before",
    "but",
    "by",
    "during",
    "for",
    "from",
    "following",
    "in",
    "inside",
    "of",
    "on",
    "over",
    "per",
    "then",
    "through",
    "under",
    "using",
    "via",
    "when",
    "where",
    "while",
    "with",
    "within",
    "without",
)


def _should_expand_document_scope(query: str, plan: RoutePlan | None) -> bool:
    if plan is None or plan.intent != "aggregation":
        return False
    tokens = normalized_match_tokens(query)
    return bool(tokens & _EXHAUSTIVE_SCOPE_TOKENS)


def _document_scope_hits(
    query: str,
    hits: list[SearchHit],
    *,
    target_doc_ids: set[str] | None = None,
) -> list[SearchHit]:
    target_doc_ids = (
        set(target_doc_ids)
        if target_doc_ids is not None
        else _target_document_ids_for_scope(query, hits)
    )
    if not target_doc_ids:
        return []
    scoped = [hit for hit in hits if _hit_doc_id(hit) in target_doc_ids]
    if _has_broad_document_scope(query):
        focused = _focused_document_scope_hits(query, scoped)
        if focused:
            scoped = focused
    return [_mark_document_scope_hit(hit) for hit in _round_robin_document_hits(scoped)]


def _target_document_ids_for_scope(query: str, hits: list[SearchHit]) -> set[str]:
    all_doc_ids = _doc_ids(hits)
    metadata_by_doc = _metadata_tokens_by_doc(hits)
    scoped_groups = _document_scope_groups(query)
    groups = [tokens for _, tokens in scoped_groups]
    typed_explicit_groups = [
        tokens for source, tokens in scoped_groups if source == "document_preposition"
    ]
    untyped_strong_groups = [
        tokens for source, tokens in scoped_groups if source == "strong_preposition"
    ]
    specific_explicit_groups = [
        tokens
        for tokens in typed_explicit_groups
        if _scope_group_specificity(tokens) > 0
    ]
    broad_groups = [
        tokens for tokens in groups if tokens <= _BROAD_DOCUMENT_SCOPE_TOKENS
    ]
    specific_action_groups = [
        tokens
        for source, tokens in scoped_groups
        if source == "action_target" and _scope_group_specificity(tokens) > 0
    ]
    bounded_action_groups = [
        tokens
        for source, tokens in scoped_groups
        if source == "bounded_action_target" and _scope_group_specificity(tokens) > 0
    ]
    if specific_explicit_groups:
        preferred_groups = specific_explicit_groups
    elif broad_groups:
        preferred_groups = broad_groups
    elif bounded_action_groups:
        preferred_groups = bounded_action_groups
    elif specific_action_groups:
        preferred_groups = specific_action_groups
    elif untyped_strong_groups:
        preferred_groups = untyped_strong_groups
    elif typed_explicit_groups:
        preferred_groups = typed_explicit_groups
    else:
        preferred_groups = groups
    if not preferred_groups:
        return set()
    max_specificity = max(
        _scope_group_specificity(tokens) for tokens in preferred_groups
    )
    matched_doc_ids: set[str] = set()
    for tokens in preferred_groups:
        if _scope_group_specificity(tokens) != max_specificity:
            continue
        if not tokens:
            continue
        if tokens <= _BROAD_DOCUMENT_SCOPE_TOKENS:
            matched_doc_ids.update(all_doc_ids)
            continue
        matched_doc_ids.update(
            _documents_matching_scope_tokens(
                tokens - _BROAD_DOCUMENT_SCOPE_TOKENS or tokens,
                metadata_by_doc,
            )
        )
    return matched_doc_ids


def _scope_group_specificity(tokens: set[str]) -> int:
    return len(
        _canonical_scope_tokens(tokens)
        - _GENERIC_SCOPE_TOKENS
        - set(_DOCUMENT_TARGET_ACTIONS)
    )


def _document_scope_token_groups(query: str) -> list[set[str]]:
    groups: list[set[str]] = []
    for _, tokens in _document_scope_groups(query):
        if tokens not in groups:
            groups.append(tokens)
    return groups


def _document_scope_groups(query: str) -> list[tuple[str, set[str]]]:
    lowered = query.lower()
    strong_preposition_pattern = (
        r"(?=\b(?:from|across|among|within)\s+(?:the\s+)?"
        r"((?:[a-z0-9][a-z0-9_-]*\s+){0,4}[a-z0-9][a-z0-9_-]*))"
    )
    typed_preposition_pattern = (
        r"(?=\b(?:in|over|through|for|of)\s+(?:the\s+)?"
        r"((?:[a-z0-9][a-z0-9_-]*\s+){0,4}[a-z0-9][a-z0-9_-]*))"
    )
    bounded_action_target_pattern = (
        rf"(?=\b(?:{'|'.join(_DOCUMENT_TARGET_ACTIONS)})\s+"
        r"(?:a\s+|an\s+|the\s+)?"
        rf"((?:[a-z0-9][a-z0-9_-]*\s+){{0,8}}(?:{'|'.join(_DOCUMENT_TARGET_NOUNS)})\b))"
    )
    action_target_pattern = (
        rf"(?=\b(?:{'|'.join(_DOCUMENT_TARGET_ACTIONS)})\s+"
        r"(?:a\s+|an\s+|the\s+)?"
        rf"([^,.;?!]*?)(?=\s+(?:and|{'|'.join(_DOCUMENT_TARGET_TRAILING_ADJUNCTS)})\b|[,.;?!]|$))"
    )
    infinitive_preposition_pattern = (
        r"(?=\bto\s+(?:the\s+)?"
        r"((?:[a-z0-9][a-z0-9_-]*\s+){0,4}[a-z0-9][a-z0-9_-]*))"
    )
    exhaustive_pattern = (
        r"(?=\b(?:all|every|each|entire|full)\s+(?:the\s+)?"
        r"((?:[a-z0-9][a-z0-9_-]*\s+){0,4}[a-z0-9][a-z0-9_-]*))"
    )
    scoped_groups: list[tuple[str, set[str]]] = []
    for source, pattern in (
        ("strong_preposition", strong_preposition_pattern),
        ("typed_preposition", typed_preposition_pattern),
        ("bounded_action_target", bounded_action_target_pattern),
        ("action_target", action_target_pattern),
        ("infinitive_preposition", infinitive_preposition_pattern),
        ("exhaustive", exhaustive_pattern),
    ):
        for match in re.finditer(pattern, lowered):
            raw_scope = match.group(1)
            tokens = _scope_tokens(raw_scope)
            resolved_source = source
            if source in {"strong_preposition", "typed_preposition"}:
                if _has_document_selector_shape(raw_scope):
                    resolved_source = "document_preposition"
                    tokens = _document_selector_scope_tokens(
                        _document_selector_head(raw_scope)
                    )
                elif source == "typed_preposition":
                    resolved_source = "adjunct_preposition"
            if tokens and (resolved_source, tokens) not in scoped_groups:
                scoped_groups.append((resolved_source, tokens))
    return scoped_groups


def _has_document_selector_shape(text: str) -> bool:
    ordered_tokens = _ordered_document_selector_tokens(text)
    kind_positions = [
        index
        for index, token in enumerate(ordered_tokens)
        if normalized_match_tokens(token)
        & (_DOCUMENT_KIND_TOKENS | _BROAD_DOCUMENT_SCOPE_TOKENS)
    ]
    if not kind_positions:
        return False
    trailing_tokens = ordered_tokens[kind_positions[-1] + 1 :]
    return all(
        token.isdecimal() or token in _DOCUMENT_SELECTOR_SUFFIX_TOKENS
        for token in trailing_tokens
    )


def _document_selector_head(text: str) -> str:
    ordered_tokens = _ordered_document_selector_tokens(text)
    kind_positions = [
        index
        for index, token in enumerate(ordered_tokens)
        if normalized_match_tokens(token)
        & (_DOCUMENT_KIND_TOKENS | _BROAD_DOCUMENT_SCOPE_TOKENS)
    ]
    if not kind_positions:
        return text
    return " ".join(ordered_tokens[: kind_positions[-1] + 1])


def _ordered_document_selector_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]*", text.casefold())
        if token not in _DOCUMENT_SCOPE_STOPWORDS
    ]


def _document_selector_scope_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(text)
        if len(token) > 2 and token not in _DOCUMENT_SCOPE_STOPWORDS
    }


def _exhaustive_document_scope_token_groups(query: str) -> list[set[str]]:
    groups: list[set[str]] = []
    pattern = (
        r"(?=\b(?:all|every|each|entire|full)\s+(?:the\s+)?"
        r"((?:[a-z0-9][a-z0-9_-]*\s+){0,4}[a-z0-9][a-z0-9_-]*))"
    )
    for match in re.finditer(pattern, query.lower()):
        tokens = _scope_tokens(match.group(1))
        if tokens and tokens not in groups:
            groups.append(tokens)
    return groups


def _requires_global_document_scope_scan(
    query: str,
    hits: list[SearchHit],
) -> bool:
    if _has_broad_document_scope(query):
        return True
    metadata_by_doc = _metadata_tokens_by_doc(hits)
    return any(
        any(
            _canonical_scope_tokens(tokens) <= _canonical_scope_tokens(metadata_tokens)
            for metadata_tokens in metadata_by_doc.values()
        )
        for tokens in _exhaustive_document_scope_token_groups(query)
    )


def _canonical_scope_tokens(tokens: set[str]) -> set[str]:
    canonical = set(tokens)
    for token in tokens:
        if token.endswith("ies") and f"{token[:-3]}y" in tokens:
            canonical.discard(token)
        elif token.endswith("s") and token[:-1] in tokens:
            canonical.discard(token)
    return canonical


def _has_broad_document_scope(query: str) -> bool:
    return any(
        tokens and tokens <= _BROAD_DOCUMENT_SCOPE_TOKENS
        for tokens in _document_scope_token_groups(query)
    )


def _has_explicit_document_scope(query: str) -> bool:
    return any(
        _canonical_scope_tokens(tokens)
        & (_DOCUMENT_KIND_TOKENS | _BROAD_DOCUMENT_SCOPE_TOKENS)
        for tokens in _document_scope_token_groups(query)
    )


def _focused_document_scope_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    focus_tokens = _document_scope_focus_tokens(query)
    if not focus_tokens:
        return []
    scored = [
        (len(focus_tokens & _hit_focus_tokens(hit)), index, hit)
        for index, hit in enumerate(hits)
    ]
    matched = [(score, index, hit) for score, index, hit in scored if score > 0]
    if not matched:
        return []
    matched_units = {
        unit for _, _, hit in matched for unit in _document_scope_unit_keys(hit)
    }
    direct_scores = {id(hit): score for score, _, hit in matched}
    selected = [
        (direct_scores.get(id(hit), 0), index, hit)
        for index, hit in enumerate(hits)
        if id(hit) in direct_scores
        or bool(matched_units & _document_scope_unit_keys(hit))
    ]
    return [
        hit
        for _, _, hit in sorted(
            selected,
            key=lambda item: (-item[0], _document_scope_sort_key(item[2]), item[1]),
        )
    ]


def _document_scope_unit_keys(hit: SearchHit) -> set[tuple[str, str, object]]:
    payload = hit.payload
    doc_id = _hit_doc_id(hit)
    keys: set[tuple[str, str, object]] = set()
    for field in ("parent_section_id", "parent_chunk_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            keys.add((doc_id, field, value.strip()))
    section_path = payload.get("section_path")
    if isinstance(section_path, list):
        normalized_path = tuple(
            str(part).strip() for part in section_path if str(part).strip()
        )
        if normalized_path:
            keys.add((doc_id, "section_path", normalized_path))
    section_title = payload.get("section_title")
    if not keys and isinstance(section_title, str) and section_title.strip():
        keys.add((doc_id, "section_title", section_title.strip().casefold()))
    return keys


def _document_scope_focus_tokens(query: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(query)
        if len(token) > 2 and token not in _DOCUMENT_SCOPE_FOCUS_STOPWORDS
    }


def _scope_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(text)
        if len(token) > 2
        and token not in _DOCUMENT_SCOPE_STOPWORDS
        and token not in _DOCUMENT_TARGET_ACTIONS
    }


def _documents_matching_scope_tokens(
    tokens: set[str], metadata_by_doc: dict[str, set[str]]
) -> set[str]:
    canonical_tokens = _canonical_scope_tokens(tokens)
    required_kinds = canonical_tokens & _DOCUMENT_KIND_TOKENS
    if not required_kinds and canonical_tokens <= _GENERIC_SUBJECT_TOKENS:
        return set()
    distinctive_tokens = canonical_tokens - _GENERIC_SCOPE_TOKENS
    scored = {
        doc_id: len(canonical_tokens & _canonical_scope_tokens(metadata_tokens))
        for doc_id, metadata_tokens in metadata_by_doc.items()
        if canonical_tokens & _canonical_scope_tokens(metadata_tokens)
        and (
            not required_kinds
            or required_kinds <= _canonical_scope_tokens(metadata_tokens)
        )
        and (
            not distinctive_tokens
            or distinctive_tokens <= _canonical_scope_tokens(metadata_tokens)
        )
    }
    if not scored:
        return set()
    best_score = max(scored.values())
    return {doc_id for doc_id, score in scored.items() if score == best_score}


def _metadata_tokens_by_doc(hits: list[SearchHit]) -> dict[str, set[str]]:
    metadata_by_doc: dict[str, set[str]] = {}
    for hit in hits:
        doc_id = _hit_doc_id(hit)
        metadata_by_doc.setdefault(doc_id, set()).update(_document_metadata_tokens(hit))
    return metadata_by_doc


def _document_metadata_tokens(hit: SearchHit) -> set[str]:
    tokens: set[str] = set()
    for field in _DOCUMENT_SCOPE_FIELDS:
        value = hit.payload.get(field)
        if isinstance(value, str):
            tokens.update(normalized_match_tokens(value))
    for field in ("tags", "document_tags"):
        value = hit.payload.get(field)
        if isinstance(value, list):
            tokens.update(
                token for item in value for token in normalized_match_tokens(item)
            )
    return tokens


def _mark_document_scope_hit(hit: SearchHit) -> SearchHit:
    payload = dict(hit.payload)
    payload["exhaustive_scope_origin"] = "document_class_scope"
    return SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)


def _round_robin_document_hits(hits: list[SearchHit]) -> list[SearchHit]:
    grouped: dict[str, list[SearchHit]] = {}
    for hit in sorted(hits, key=_document_scope_sort_key):
        grouped.setdefault(_hit_doc_id(hit), []).append(hit)
    ordered: list[SearchHit] = []
    index = 0
    while True:
        added = False
        for doc_id in sorted(grouped):
            group = grouped[doc_id]
            if index < len(group):
                ordered.append(group[index])
                added = True
        if not added:
            return ordered
        index += 1


def _document_scope_sort_key(hit: SearchHit) -> tuple[str, int, int, str]:
    payload = hit.payload
    return (
        str(payload.get("doc_title") or payload.get("doc_id") or ""),
        _optional_int(payload.get("page_start"))
        or _optional_int(payload.get("page"))
        or 10**9,
        _optional_int(payload.get("table_row_index")) or 0,
        str(payload.get("chunk_id", hit.point_id)),
    )
