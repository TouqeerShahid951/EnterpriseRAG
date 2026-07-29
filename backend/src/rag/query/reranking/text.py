"""Text normalization and hit identity helpers shared by reranking policies."""

from __future__ import annotations

from rag.shared.contracts.structured_payloads import (
    normalized_match_tokens,
    normalized_phrase,
    normalized_tokens,
)

from ..qdrant import SearchHit

_STOPWORDS = {
    "about",
    "after",
    "before",
    "does",
    "from",
    "have",
    "into",
    "that",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def hit_doc_id(hit: SearchHit) -> str:
    return str(hit.payload.get("doc_id") or hit.point_id)


def payload_str(hit: SearchHit, field: str) -> str:
    value = hit.payload.get(field)
    return value.strip() if isinstance(value, str) else ""


def payload_int(hit: SearchHit, field: str) -> int | None:
    value = hit.payload.get(field)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    return None


def hit_page(hit: SearchHit) -> int | None:
    for field in ("page_start", "page", "parent_page_start"):
        value = payload_int(hit, field)
        if value is not None:
            return value
    return None


def unique_hits(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        key = hit_identity(hit)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def hit_identity(hit: SearchHit) -> tuple[str, str, str]:
    return (
        str(hit.payload.get("doc_id", "")),
        str(hit.payload.get("chunk_id", hit.point_id)),
        hit.point_id,
    )


def searchable_text(hit: SearchHit) -> str:
    payload = hit.payload
    parts: list[str] = []
    structured_search_text = payload.get("structured_search_text")
    if isinstance(structured_search_text, str) and structured_search_text.strip():
        parts.append(structured_search_text)
    for key in (
        "doc_title",
        "doc_summary",
        "text",
        "summary",
        "table_title",
        "table_caption",
        "table_row_label",
        "section_title",
        "generated_doc_type",
        "doc_type",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    headers = payload.get("table_column_headers")
    if isinstance(headers, list):
        parts.extend(str(header) for header in headers)
    section_path = payload.get("section_path")
    if isinstance(section_path, list):
        parts.extend(str(part) for part in section_path)
    return " ".join(parts)


def reranker_text(hit: SearchHit, *, max_chars: int) -> str:
    """Format one bounded passage while keeping chunk evidence ahead of summaries."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    payload = hit.payload
    descriptor_parts: list[str] = []
    for label, field in (
        ("Title", "doc_title"),
        ("Section", "section_title"),
        ("Table", "table_title"),
        ("Caption", "table_caption"),
        ("Row", "table_row_label"),
        ("Type", "doc_type"),
    ):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            descriptor_parts.append(f"{label}: {value.strip()}")
    section_path = payload.get("section_path")
    if isinstance(section_path, list):
        path = " / ".join(str(part).strip() for part in section_path if str(part).strip())
        if path:
            descriptor_parts.append(f"Path: {path}")
    headers = payload.get("table_column_headers")
    if isinstance(headers, list):
        header_text = " | ".join(str(header).strip() for header in headers if str(header).strip())
        if header_text:
            descriptor_parts.append(f"Columns: {header_text}")

    descriptor_limit = min(320, max_chars // 4)
    structured_limit = max_chars // 3
    parts = ["\n".join(descriptor_parts)[:descriptor_limit]]
    structured = payload.get("structured_search_text")
    if isinstance(structured, str):
        parts.append(structured.strip()[:structured_limit])
    for field in ("text", "summary", "doc_summary"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(part for part in parts if part)[:max_chars]


def tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_tokens(text)
        if len(token) > 2 and token not in _STOPWORDS
    }


def match_tokens(text: str) -> set[str]:
    return {
        token
        for token in normalized_match_tokens(text)
        if len(token) > 2 and token not in _STOPWORDS
    }


def normalized_text(text: object) -> str:
    return normalized_phrase(text)


def normalized_query_phrases(query: str) -> set[str]:
    query_tokens = [token for token in normalized_phrase(query).split() if token]
    phrases: set[str] = set()
    for size in range(2, min(6, len(query_tokens)) + 1):
        phrases.update(
            " ".join(query_tokens[index : index + size])
            for index in range(0, len(query_tokens) - size + 1)
        )
    return phrases
