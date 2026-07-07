"""Source, citation, highlight, and evidence helpers for query responses."""

from __future__ import annotations

import hashlib
import re

from ..schemas.query import EvidenceField, HighlightRange, SourceAnchor, SourceRegion
from ..shared.contracts.clearance import normalize_clearance_level
from .qdrant import SearchHit

_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_EXACT_VALUE_RE = re.compile(
    r"\b(?:\d[\d,./:-]{1,}\d|[A-Za-z]+[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*|\d[A-Za-z0-9_-]*[A-Za-z][A-Za-z0-9_-]*)\b"
)
_STOPWORDS = {
    "about",
    "does",
    "from",
    "how",
    "the",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
}
_COVERAGE_STOPWORDS = _STOPWORDS | {
    "and",
    "are",
    "can",
    "could",
    "for",
    "has",
    "have",
    "into",
    "list",
    "listed",
    "show",
    "tell",
    "that",
    "this",
    "was",
    "were",
    "will",
    "with",
    "would",
}
PARENT_PROMOTION_MAX_CHARS = 4096
COVERAGE_RESERVE_LIMIT = 3
COVERAGE_HEAD_LIMIT = 1
_STRUCTURED_QUERY_TERMS = {
    "amount",
    "column",
    "columns",
    "code",
    "date",
    "digit",
    "digits",
    "field",
    "fields",
    "form",
    "header",
    "id",
    "identifier",
    "job",
    "number",
    "numbers",
    "row",
    "rows",
    "sequence",
    "service",
    "table",
    "title",
    "total",
    "value",
}


def citation_label(doc_id: str, chunk_id: str) -> str:
    if chunk_id.startswith(f"{doc_id}:"):
        return f"[{chunk_id}]"
    return f"[{doc_id}:{chunk_id}]"


def source_citation(source: SourceAnchor) -> str:
    return citation_label(source.doc_id, source.chunk_id)


def source_from_hit(hit: SearchHit, *, query: str = "") -> SourceAnchor:
    payload = hit.payload
    excerpt = payload_text(hit)
    page = optional_int(payload.get("page"))
    page_start = optional_int(payload.get("page_start")) or page
    page_end = optional_int(payload.get("page_end")) or page_start
    return SourceAnchor(
        doc_id=str(payload.get("doc_id", hit.point_id)),
        doc_title=str(payload.get("doc_title", "Untitled")),
        chunk_id=str(payload.get("chunk_id", hit.point_id)),
        page=page or page_start,
        page_start=page_start,
        page_end=page_end,
        excerpt=excerpt,
        group_path=str(payload.get("group_path", "/local")),
        clearance_level=normalize_clearance_level(payload.get("clearance_level")),
        effective_date=optional_str(payload.get("effective_date")),
        highlight_ranges=build_highlights(query, excerpt) if query else [],
        source_regions=source_regions_from_payload(payload),
        attribution_kind="table_row" if str(payload.get("structured_kind", "")) == "table_row" else "text",
        attribution_table_title=optional_str(payload.get("table_title")) or "",
        attribution_fields=structured_fields_from_payload(payload),
    )


def payload_text(hit: SearchHit) -> str:
    text = hit.payload.get("text")
    return text.strip() if isinstance(text, str) else ""


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def source_regions_from_payload(payload: dict[str, object]) -> list[SourceRegion]:
    raw_regions = payload.get("source_regions")
    if not isinstance(raw_regions, list):
        return []
    regions: list[SourceRegion] = []
    for raw_region in raw_regions:
        if not isinstance(raw_region, dict):
            continue
        normalized_bbox = optional_bbox(raw_region.get("bbox"))
        page = optional_int(raw_region.get("page"))
        text = raw_region.get("text")
        region_type = raw_region.get("region_type")
        confidence = raw_region.get("confidence")
        image_asset_id = raw_region.get("image_asset_id")
        image_source_kind = raw_region.get("image_source_kind")
        extraction_method = raw_region.get("extraction_method")
        regions.append(
            SourceRegion(
                page=page,
                bbox=normalized_bbox,
                text=text if isinstance(text, str) else "",
                region_type=region_type if isinstance(region_type, str) and region_type else "text",
                confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
                image_asset_id=image_asset_id if isinstance(image_asset_id, str) and image_asset_id else None,
                image_source_kind=image_source_kind if isinstance(image_source_kind, str) and image_source_kind else None,
                extraction_method=extraction_method if isinstance(extraction_method, str) and extraction_method else None,
            )
        )
    return regions


def structured_fields_from_payload(payload: dict[str, object]) -> list[EvidenceField]:
    raw_fields = payload.get("structured_fields")
    if not isinstance(raw_fields, list):
        return []
    fields: list[EvidenceField] = []
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            continue
        label = raw_field.get("label")
        value = raw_field.get("value")
        if not isinstance(label, str) or not label.strip() or not isinstance(value, str) or not value.strip():
            continue
        fields.append(EvidenceField(label=label.strip(), value=value.strip()))
    return fields


def optional_bbox(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def build_highlights(query: str, excerpt: str, *, max_ranges: int = 6) -> list[HighlightRange]:
    ranges: list[tuple[int, int]] = []
    for term in _query_terms(query):
        for match in re.finditer(rf"\b{re.escape(term)}\b", excerpt, flags=re.IGNORECASE):
            ranges.append((match.start(), match.end()))
            if len(ranges) >= max_ranges:
                return _merge_ranges(ranges)
    return _merge_ranges(ranges)


def dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[str] = set()
    unique: list[SearchHit] = []
    for hit in hits:
        keys = _dedupe_keys(hit)
        if seen & keys:
            continue
        seen.update(keys)
        unique.append(hit)
    return unique


def build_evidence_hits(
    hits: list[SearchHit],
    *,
    token_budget: int,
    limit: int,
    broader_table_context: bool = False,
    query: str = "",
) -> list[SearchHit]:
    candidates = dedupe_hits(hits)
    if broader_table_context:
        candidates = dedupe_hits(_promote_parent_text(candidates))
    candidates = _with_coverage_reserve(candidates, query)
    return _hits_within_budget(candidates, token_budget=token_budget, limit=limit)


def sources_from_hits(hits: list[SearchHit], *, query: str = "") -> list[SourceAnchor]:
    return [source_from_hit(hit, query=query) for hit in dedupe_hits(hits) if payload_text(hit)]


def _query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for match in _TERM_RE.finditer(query.lower()):
        term = match.group(0)
        if term in _STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _coverage_terms(query: str) -> list[str]:
    return [term for term in _query_terms(query) if term not in _COVERAGE_STOPWORDS]


def _with_coverage_reserve(hits: list[SearchHit], query: str) -> list[SearchHit]:
    terms = _coverage_terms(query)
    exact_values = _exact_values(query)
    if not terms and not exact_values:
        return hits

    scored: list[tuple[int, int, SearchHit]] = []
    wants_structured = any(term in _STRUCTURED_QUERY_TERMS for term in terms)
    for index, hit in enumerate(hits):
        score = _coverage_score(hit, terms=terms, exact_values=exact_values, wants_structured=wants_structured)
        if score > 0:
            scored.append((score, index, hit))
    if not scored:
        return hits

    reserve = [
        hit for _, _, hit in sorted(scored, key=lambda item: (-item[0], item[1]))[:COVERAGE_RESERVE_LIMIT]
    ]
    if not reserve:
        return hits

    ordered: list[SearchHit] = []
    seen: set[str] = set()

    def add(hit: SearchHit) -> None:
        key = str(hit.payload.get("chunk_id") or hit.point_id)
        if key in seen:
            return
        seen.add(key)
        ordered.append(hit)

    for hit in hits[:COVERAGE_HEAD_LIMIT]:
        add(hit)
    for hit in reserve:
        add(hit)
    for hit in hits[COVERAGE_HEAD_LIMIT:]:
        add(hit)
    return ordered


def _coverage_score(
    hit: SearchHit,
    *,
    terms: list[str],
    exact_values: list[str],
    wants_structured: bool,
) -> int:
    text = _coverage_text(hit)
    if not text:
        return 0

    compact_text = _compact_value_text(text)
    exact_matches = sum(1 for value in exact_values if _compact_value_text(value) in compact_text)
    specific_terms = [term for term in terms if term not in _STRUCTURED_QUERY_TERMS]
    specific_matches = sum(1 for term in specific_terms if _term_in_text(term, text))
    structured_matches = sum(1 for term in terms if term in _STRUCTURED_QUERY_TERMS and _term_in_text(term, text))

    if not exact_matches and not specific_matches and not structured_matches:
        return 0

    score = exact_matches * 8 + min(specific_matches, 6) * 2 + min(structured_matches, 3)
    if wants_structured and _is_structured_hit(hit):
        score += 4
    return score


def _coverage_text(hit: SearchHit) -> str:
    payload = hit.payload
    parts = [payload_text(hit)]
    for key in ("doc_title", "section_title", "heading", "table_title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    raw_fields = payload.get("structured_fields")
    if isinstance(raw_fields, list):
        for raw_field in raw_fields:
            if not isinstance(raw_field, dict):
                continue
            label = raw_field.get("label")
            value = raw_field.get("value")
            if isinstance(label, str):
                parts.append(label)
            if isinstance(value, str):
                parts.append(value)
    return _normalized_text(" ".join(parts))


def _is_structured_hit(hit: SearchHit) -> bool:
    payload = hit.payload
    if str(payload.get("structured_kind", "")) == "table_row":
        return True
    if str(payload.get("chunk_type", "")) in {"form", "form_field", "table", "table_row"}:
        return True
    raw_fields = payload.get("structured_fields")
    return isinstance(raw_fields, list) and bool(raw_fields)


def _exact_values(query: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for match in _EXACT_VALUE_RE.finditer(query):
        value = match.group(0).lower()
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _term_in_text(term: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE) is not None


def _compact_value_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[HighlightRange]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return [HighlightRange(start=start, end=end) for start, end in merged]


def _dedupe_keys(hit: SearchHit) -> set[str]:
    chunk_id = hit.payload.get("chunk_id") or hit.point_id
    keys = {f"chunk:{chunk_id}"}
    text = payload_text(hit)
    if text:
        keys.add(f"text:{hashlib.sha256(_normalized_text(text).encode()).hexdigest()}")
    for field in ("chunk_content_hash", "text_hash"):
        value = hit.payload.get(field)
        if isinstance(value, str) and value:
            keys.add(f"{field}:{value}")
    return keys


def _promote_parent_text(hits: list[SearchHit]) -> list[SearchHit]:
    promoted: list[SearchHit] = []
    for hit in hits:
        parent_text = _parent_text(hit)
        parent_page_start = optional_int(hit.payload.get("parent_page_start"))
        parent_page_end = optional_int(hit.payload.get("parent_page_end")) or parent_page_start
        if not parent_text or parent_page_start is None:
            promoted.append(hit)
            continue
        payload = {
            **hit.payload,
            "text": _bounded_parent_text(parent_text, payload_text(hit)),
            "page": parent_page_start,
            "page_start": parent_page_start,
            "page_end": parent_page_end,
        }
        promoted.append(SearchHit(point_id=hit.point_id, score=hit.score, payload=payload))
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


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def _hits_within_budget(hits: list[SearchHit], *, token_budget: int, limit: int) -> list[SearchHit]:
    selected: list[SearchHit] = []
    used_tokens = 0
    for hit in hits:
        text = payload_text(hit)
        if not text:
            continue
        estimated_tokens = max(1, len(text) // 4)
        if estimated_tokens > token_budget or used_tokens + estimated_tokens > token_budget:
            continue
        selected.append(hit)
        used_tokens += estimated_tokens
        if len(selected) >= limit:
            break
    return selected
