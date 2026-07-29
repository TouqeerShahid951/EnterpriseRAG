"""Mapping retrieval hits to source anchors and query highlights."""

from __future__ import annotations

import re

from rag.shared.contracts.clearance import normalize_clearance_level
from rag.shared.contracts.evidence import (
    EvidenceField,
    HighlightRange,
    SourceAnchor,
    SourceRegion,
)
from rag.query.qdrant import SearchHit

_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_CITATION_TOKEN_RE = re.compile(
    r"\[[^\[\]\r\n]{1,200}:[^\[\]\r\n]{1,200}\]"
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


def citation_label(doc_id: str, chunk_id: str) -> str:
    if chunk_id.startswith(f"{doc_id}:"):
        return f"[{chunk_id}]"
    return f"[{doc_id}:{chunk_id}]"


def source_citation(source: SourceAnchor) -> str:
    return citation_label(source.doc_id, source.chunk_id)


def parse_citation_tokens(text: str) -> tuple[str, ...]:
    """Return citation-shaped tokens in occurrence order, including duplicates."""

    return tuple(match.group(0) for match in _CITATION_TOKEN_RE.finditer(text))


def source_from_hit(hit: SearchHit, *, query: str = "") -> SourceAnchor:
    payload = hit.payload
    excerpt = payload_text(hit)
    page = optional_int(payload.get("page"))
    page_start = optional_int(payload.get("page_start")) or page
    page_end = optional_int(payload.get("page_end")) or page_start
    structured_kind = str(payload.get("structured_kind", ""))
    is_live_database = str(payload.get("source_type", "")).startswith(
        "connector_live_sql"
    )
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
        attribution_kind="table_row"
        if structured_kind == "table_row"
        or (is_live_database and structured_kind == "kv_record")
        else "text",
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
                region_type=region_type
                if isinstance(region_type, str) and region_type
                else "text",
                confidence=float(confidence)
                if isinstance(confidence, (int, float))
                else None,
                image_asset_id=image_asset_id
                if isinstance(image_asset_id, str) and image_asset_id
                else None,
                image_source_kind=image_source_kind
                if isinstance(image_source_kind, str) and image_source_kind
                else None,
                extraction_method=extraction_method
                if isinstance(extraction_method, str) and extraction_method
                else None,
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
        if (
            not isinstance(label, str)
            or not label.strip()
            or not isinstance(value, str)
            or not value.strip()
        ):
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


def build_highlights(
    query: str, excerpt: str, *, max_ranges: int = 6
) -> list[HighlightRange]:
    ranges: list[tuple[int, int]] = []
    for term in _query_terms(query):
        for match in re.finditer(
            rf"\b{re.escape(term)}\b", excerpt, flags=re.IGNORECASE
        ):
            ranges.append((match.start(), match.end()))
            if len(ranges) >= max_ranges:
                return _merge_ranges(ranges)
    return _merge_ranges(ranges)


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


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())
