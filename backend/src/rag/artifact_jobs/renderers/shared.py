"""Shared deterministic text and citation formatting for artifact renderers."""

from __future__ import annotations

import re

from ..contracts import ContentBlock, EvidenceCitation


PPTX_MAX_SOURCE_LABELS = 5


def _list_items(block: ContentBlock) -> list[tuple[str, list[str]]]:
    if block.list_items:
        return [(item.text, item.evidence_ids) for item in block.list_items]
    return [(item, block.evidence_ids) for item in block.items]


def _with_sources(text: str, evidence_ids: list[str], citations: dict[str, EvidenceCitation]) -> str:
    summary = _source_summary(evidence_ids, citations)
    return f"{text} ({summary})" if summary else text


def _source_summary(evidence_ids: list[str], citations: dict[str, EvidenceCitation]) -> str:
    labels = list(dict.fromkeys([
        _short_citation(citations[evidence_id])
        for evidence_id in evidence_ids
        if evidence_id in citations
    ]))
    if len(labels) > PPTX_MAX_SOURCE_LABELS:
        labels = [*labels[:PPTX_MAX_SOURCE_LABELS], f"+{len(labels) - PPTX_MAX_SOURCE_LABELS} more"]
    return "Sources: " + "; ".join(labels) if labels else ""


def _short_citation(citation: EvidenceCitation) -> str:
    return f"{citation.doc_title}, p. {citation.page_start}" if citation.page_start else citation.doc_title


def _reference_line(index: int, citation: EvidenceCitation) -> str:
    page = ""
    if citation.page_start is not None and citation.page_end not in (None, citation.page_start):
        page = f", pages {citation.page_start}-{citation.page_end}"
    elif citation.page_start is not None:
        page = f", page {citation.page_start}"
    return f"[{index}] {citation.doc_title}{page} ({citation.doc_id}:{citation.chunk_id})"


def _safe_filename(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return _compact(candidate or "evidence-artifact", 80).strip(".-") or "evidence-artifact"


def _compact(value: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= limit else normalized[: max(0, limit - 3)].rstrip() + "..."
