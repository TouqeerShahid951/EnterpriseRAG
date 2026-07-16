"""Compatibility facade for query source and evidence helpers."""

from __future__ import annotations

import hashlib as hashlib
import re as re

from rag.shared.contracts.clearance import (
    normalize_clearance_level as normalize_clearance_level,
)
from rag.shared.contracts.evidence import (
    EvidenceField as EvidenceField,
    HighlightRange as HighlightRange,
    SourceAnchor as SourceAnchor,
    SourceRegion as SourceRegion,
)
from rag.query.qdrant import SearchHit as SearchHit
from rag.query.sources.source_context_budget import _hits_within_budget as _hits_within_budget
from rag.query.sources.source_evidence_selection import (
    COVERAGE_HEAD_LIMIT as COVERAGE_HEAD_LIMIT,
    COVERAGE_RESERVE_LIMIT as COVERAGE_RESERVE_LIMIT,
    _COVERAGE_STOPWORDS as _COVERAGE_STOPWORDS,
    _EXACT_VALUE_RE as _EXACT_VALUE_RE,
    _STRUCTURED_QUERY_TERMS as _STRUCTURED_QUERY_TERMS,
    _compact_value_text as _compact_value_text,
    _coverage_score as _coverage_score,
    _coverage_terms as _coverage_terms,
    _coverage_text as _coverage_text,
    _dedupe_keys as _dedupe_keys,
    _exact_values as _exact_values,
    _is_structured_hit as _is_structured_hit,
    _term_in_text as _term_in_text,
    _with_coverage_reserve as _with_coverage_reserve,
    build_evidence_hits as build_evidence_hits,
    dedupe_hits as dedupe_hits,
    sources_from_hits as sources_from_hits,
)
from rag.query.sources.source_mapping import (
    _STOPWORDS as _STOPWORDS,
    _TERM_RE as _TERM_RE,
    _merge_ranges as _merge_ranges,
    _normalized_text as _normalized_text,
    _query_terms as _query_terms,
    build_highlights as build_highlights,
    citation_label as citation_label,
    optional_bbox as optional_bbox,
    optional_int as optional_int,
    optional_str as optional_str,
    parse_citation_tokens as parse_citation_tokens,
    payload_text as payload_text,
    source_citation as source_citation,
    source_from_hit as source_from_hit,
    source_regions_from_payload as source_regions_from_payload,
    structured_fields_from_payload as structured_fields_from_payload,
)
from rag.query.sources.source_parent_promotion import (
    PARENT_PROMOTION_MAX_CHARS as PARENT_PROMOTION_MAX_CHARS,
    _bounded_parent_text as _bounded_parent_text,
    _parent_anchor_index as _parent_anchor_index,
    _parent_anchor_needles as _parent_anchor_needles,
    _parent_text as _parent_text,
    _promote_parent_text as _promote_parent_text,
)

__all__ = [
    "COVERAGE_HEAD_LIMIT",
    "COVERAGE_RESERVE_LIMIT",
    "EvidenceField",
    "HighlightRange",
    "PARENT_PROMOTION_MAX_CHARS",
    "SearchHit",
    "SourceAnchor",
    "SourceRegion",
    "build_evidence_hits",
    "build_highlights",
    "citation_label",
    "dedupe_hits",
    "hashlib",
    "normalize_clearance_level",
    "optional_bbox",
    "optional_int",
    "optional_str",
    "parse_citation_tokens",
    "payload_text",
    "re",
    "source_citation",
    "source_from_hit",
    "source_regions_from_payload",
    "sources_from_hits",
    "structured_fields_from_payload",
]
