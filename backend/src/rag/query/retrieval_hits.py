"""Shared hit accessors for retrieval policies."""

from __future__ import annotations

from rag.shared.contracts.structured_payloads import normalized_match_tokens

from .qdrant import SearchHit


def _hit_focus_tokens(hit: SearchHit) -> set[str]:
    return {
        token
        for part in _hit_focus_parts(hit)
        for token in normalized_match_tokens(part)
    }


def _hit_focus_text(hit: SearchHit) -> str:
    return " ".join(_hit_focus_parts(hit))


def _hit_focus_parts(hit: SearchHit) -> list[str]:
    payload = hit.payload
    parts: list[str] = []
    for field in (
        "doc_title",
        "doc_summary",
        "doc_type",
        "generated_doc_type",
        "auto_doc_type",
        "section_title",
        "table_title",
        "table_caption",
        "table_row_label",
        "text",
        "parent_text",
        "structured_search_text",
    ):
        value = payload.get(field)
        if isinstance(value, str):
            parts.append(value)
    for field in (
        "topics",
        "llm_topics",
        "metadata_terms",
        "section_path",
        "table_column_headers",
    ):
        value = payload.get(field)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return parts


def _doc_ids(hits: list[SearchHit]) -> set[str]:
    return {_hit_doc_id(hit) for hit in hits}


def _hit_doc_id(hit: SearchHit) -> str:
    return str(hit.payload.get("doc_id", hit.point_id))


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None
