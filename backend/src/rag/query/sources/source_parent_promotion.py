"""Promotion and bounding of parent context for structured retrieval hits."""

from __future__ import annotations

from rag.query.qdrant import SearchHit
from rag.query.sources.source_mapping import optional_int, payload_text

PARENT_PROMOTION_MAX_CHARS = 4096


def _promote_parent_text(hits: list[SearchHit]) -> list[SearchHit]:
    promoted: list[SearchHit] = []
    for hit in hits:
        parent_text = _parent_text(hit)
        parent_page_start = optional_int(hit.payload.get("parent_page_start"))
        parent_page_end = (
            optional_int(hit.payload.get("parent_page_end")) or parent_page_start
        )
        if not parent_text:
            promoted.append(hit)
            continue
        child_text = payload_text(hit)
        if len(parent_text) < len(child_text):
            promoted.append(hit)
            continue
        payload = {
            **hit.payload,
            "citation_original_text": hit.payload.get("citation_original_text", hit.payload.get("text", child_text)),
            "text": _bounded_parent_text(parent_text, child_text),
            "page_start": hit.payload.get("page_start") or hit.payload.get("page"),
            "page_end": hit.payload.get("page_end") or hit.payload.get("page_start") or hit.payload.get("page"),
        }
        if parent_page_start is not None:
            payload.update(
                {
                    "context_page_start": parent_page_start,
                    "context_page_end": parent_page_end,
                }
            )
        promoted.append(
            SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)
        )
    return promoted


def _parent_text(hit: SearchHit) -> str:
    for field in ("parent_text", "parent_content", "section_text"):
        value = hit.payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _bounded_parent_text(parent_text: str, child_text: str) -> str:
    if len(parent_text) <= PARENT_PROMOTION_MAX_CHARS:
        return parent_text
    anchor = _parent_anchor_index(parent_text, child_text)
    if anchor < 0:
        return parent_text[:PARENT_PROMOTION_MAX_CHARS].rstrip()
    start = max(0, anchor - PARENT_PROMOTION_MAX_CHARS // 2)
    end = start + PARENT_PROMOTION_MAX_CHARS
    if end > len(parent_text):
        end = len(parent_text)
        start = max(0, end - PARENT_PROMOTION_MAX_CHARS)
    return parent_text[start:end].strip()


def _parent_anchor_index(parent_text: str, child_text: str) -> int:
    parent_lower = parent_text.lower()
    for needle in _parent_anchor_needles(child_text):
        index = parent_text.find(needle)
        if index >= 0:
            return index
        index = parent_lower.find(needle.lower())
        if index >= 0:
            return index
    return -1


def _parent_anchor_needles(child_text: str) -> list[str]:
    needles: list[str] = []
    for line in child_text.splitlines():
        needle = line.strip()
        if needle.startswith("[Columns:"):
            continue
        if needle.startswith(("Row:", "Value:")):
            needle = needle.split(":", 1)[1].strip()
        if len(needle) >= 8:
            needles.append(needle[:160])
    return sorted(dict.fromkeys(needles), key=len, reverse=True)
