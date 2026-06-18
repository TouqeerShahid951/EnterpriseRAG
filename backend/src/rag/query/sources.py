"""Source, citation, highlight, and evidence helpers for query responses."""

from __future__ import annotations

import hashlib
import re

from ..schemas.query import EvidenceField, HighlightRange, SourceAnchor, SourceRegion
from ..shared.contracts.clearance import normalize_clearance_level
from .qdrant import SearchHit

_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_LOW_INFORMATION_REFERENCE_RE = re.compile(r"^(?:table|figure)\s+\d+[\.:]", re.IGNORECASE)
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
) -> list[SearchHit]:
    candidates = _prioritize_substantive_hits(dedupe_hits(_promote_parent_text(dedupe_hits(hits))))
    scoped_order = _exhaustive_scope_order(candidates)
    if scoped_order:
        return _hits_within_budget(scoped_order, token_budget=token_budget, limit=limit)
    direct_structured = [hit for hit in candidates if _is_direct_structured_hit(hit)]
    structured_group_order = _round_robin_hits(_grouped_hits(direct_structured))
    context_hits = _structured_context_hits(candidates, direct_structured)
    sibling_cap = limit if broader_table_context else 4
    sibling_hits = _round_robin_hits(_grouped_hits([hit for hit in candidates if _is_sibling_structured_hit(hit)], per_group_limit=sibling_cap))
    remaining_hits = [
        hit
        for hit in candidates
        if not _is_direct_structured_hit(hit)
        and not _is_sibling_structured_hit(hit)
        and not _is_context_marker_hit(hit)
    ]
    ordered = dedupe_hits([*context_hits, *structured_group_order, *sibling_hits, *remaining_hits])
    return _hits_within_budget(ordered, token_budget=token_budget, limit=limit)


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
        if _is_structured_hit(hit):
            promoted.append(hit)
            continue
        parent_text = _parent_text(hit)
        parent_page_start = optional_int(hit.payload.get("parent_page_start"))
        parent_page_end = optional_int(hit.payload.get("parent_page_end")) or parent_page_start
        if not parent_text or parent_page_start is None:
            promoted.append(hit)
            continue
        payload = {
            **hit.payload,
            "text": parent_text,
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


def _prioritize_substantive_hits(hits: list[SearchHit]) -> list[SearchHit]:
    substantive: list[SearchHit] = []
    low_information: list[SearchHit] = []
    for hit in hits:
        if _is_low_information_reference(payload_text(hit)):
            low_information.append(hit)
        else:
            substantive.append(hit)
    return substantive + low_information


def _is_low_information_reference(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if len(normalized) > 160:
        return False
    if not _LOW_INFORMATION_REFERENCE_RE.match(normalized):
        return False
    detailed_markers = ("controller features", "\uf0b7", "•", " rows:", " form factor ")
    return not any(marker in normalized for marker in detailed_markers)


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
        if selected and used_tokens + estimated_tokens > token_budget:
            continue
        selected.append(hit)
        used_tokens += estimated_tokens
        if len(selected) >= limit:
            break
    return selected


def _is_structured_hit(hit: SearchHit) -> bool:
    structured_kind = hit.payload.get("structured_kind")
    if isinstance(structured_kind, str) and structured_kind.strip():
        return True
    if hit.payload.get("chunk_type") == "table_row":
        return True
    table_json = hit.payload.get("table_json")
    return isinstance(table_json, dict) and bool(table_json)


def _is_direct_structured_hit(hit: SearchHit) -> bool:
    return _is_structured_hit(hit) and str(hit.payload.get("structured_origin", "direct")) != "sibling"


def _is_sibling_structured_hit(hit: SearchHit) -> bool:
    return _is_structured_hit(hit) and str(hit.payload.get("structured_origin", "")) == "sibling"


def _structured_group_key(hit: SearchHit) -> tuple[str, str]:
    payload = hit.payload
    doc_id = str(payload.get("doc_id", hit.point_id))
    table_title = payload.get("table_title")
    if isinstance(table_title, str) and table_title.strip():
        return doc_id, f"table:{table_title.strip()}"
    parent_chunk_id = payload.get("parent_chunk_id")
    if isinstance(parent_chunk_id, str) and parent_chunk_id.strip():
        return doc_id, f"parent:{parent_chunk_id.strip()}"
    parent_section_id = payload.get("parent_section_id")
    if isinstance(parent_section_id, str) and parent_section_id.strip():
        return doc_id, f"section:{parent_section_id.strip()}"
    return doc_id, f"chunk:{str(payload.get('chunk_id', hit.point_id))}"


def _grouped_hits(hits: list[SearchHit], *, per_group_limit: int | None = None) -> list[list[SearchHit]]:
    groups: dict[tuple[str, str], list[SearchHit]] = {}
    order: list[tuple[str, str]] = []
    for hit in hits:
        key = _structured_group_key(hit)
        if key not in groups:
            groups[key] = []
            order.append(key)
        if per_group_limit is None or len(groups[key]) < per_group_limit:
            groups[key].append(hit)
    return [groups[key] for key in order]


def _round_robin_hits(groups: list[list[SearchHit]]) -> list[SearchHit]:
    ordered: list[SearchHit] = []
    index = 0
    while True:
        added = False
        for group in groups:
            if index < len(group):
                ordered.append(group[index])
                added = True
        if not added:
            return ordered
        index += 1


def _exhaustive_scope_order(candidates: list[SearchHit]) -> list[SearchHit]:
    scoped = [hit for hit in candidates if _is_exhaustive_scope_hit(hit)]
    if not scoped:
        return []
    remaining = [hit for hit in candidates if not _is_exhaustive_scope_hit(hit)]
    return dedupe_hits([*_round_robin_hits(_grouped_hits_by_doc(scoped)), *remaining])


def _is_exhaustive_scope_hit(hit: SearchHit) -> bool:
    return str(hit.payload.get("exhaustive_scope_origin", "")) == "document_class_scope"


def _grouped_hits_by_doc(hits: list[SearchHit]) -> list[list[SearchHit]]:
    groups: dict[str, list[SearchHit]] = {}
    order: list[str] = []
    for hit in hits:
        doc_id = str(hit.payload.get("doc_id", hit.point_id))
        if doc_id not in groups:
            groups[doc_id] = []
            order.append(doc_id)
        groups[doc_id].append(hit)
    return [groups[doc_id] for doc_id in order]


def _structured_context_hits(candidates: list[SearchHit], direct_hits: list[SearchHit]) -> list[SearchHit]:
    contexts: list[SearchHit] = []
    seen_groups: set[tuple[str, str]] = set()
    for hit in direct_hits:
        key = _structured_group_key(hit)
        if key in seen_groups:
            continue
        seen_groups.add(key)
        context = _existing_context_hit(candidates, key)
        if context is None:
            context = _parent_context_hit(hit)
        if context is not None:
            contexts.append(context)
    return contexts


def _existing_context_hit(candidates: list[SearchHit], key: tuple[str, str]) -> SearchHit | None:
    for hit in candidates:
        if _structured_group_key(hit) != key:
            continue
        if _is_direct_structured_hit(hit) or _is_sibling_structured_hit(hit):
            continue
        if payload_text(hit):
            return _mark_context_hit(hit)
    return None


def _parent_context_hit(hit: SearchHit) -> SearchHit | None:
    parent_text = _parent_text(hit)
    parent_page_start = optional_int(hit.payload.get("parent_page_start"))
    parent_page_end = optional_int(hit.payload.get("parent_page_end")) or parent_page_start
    if not parent_text or parent_page_start is None:
        return None
    payload = {
        **hit.payload,
        "text": parent_text,
        "page": parent_page_start,
        "page_start": parent_page_start,
        "page_end": parent_page_end,
        "structured_origin": "context",
    }
    return SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)


def _mark_context_hit(hit: SearchHit) -> SearchHit:
    payload = dict(hit.payload)
    payload["structured_origin"] = "context"
    return SearchHit(point_id=hit.point_id, score=hit.score, payload=payload)


def _is_context_marker_hit(hit: SearchHit) -> bool:
    return str(hit.payload.get("structured_origin", "")) == "context"
