"""Shared helpers for artifact sandbox SDK builders."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from rag.artifact_jobs.contracts import EvidenceCitation


def normalize_evidence_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict):
        return normalize_evidence_ids(value.get("evidence_id") or value.get("id") or value.get("evidence_ids"))
    if isinstance(value, (list, tuple, set)):
        flattened: list[str] = []
        for item in value:
            flattened.extend(normalize_evidence_ids(item))
        return list(dict.fromkeys(flattened))
    evidence_id = getattr(value, "evidence_id", None)
    if evidence_id is not None:
        return normalize_evidence_ids(evidence_id)
    evidence_ids = getattr(value, "evidence_ids", None)
    if evidence_ids is not None:
        return normalize_evidence_ids(evidence_ids)
    return []


def validated_output_path(path: str) -> Path:
    out_dir = Path(os.environ.get("ARTIFACT_SANDBOX_OUT_DIR", "/work/out")).resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(out_dir):
        raise RuntimeError("artifact SDK can write only under /work/out")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def compact(value: object, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def citation_map(citations: list[EvidenceCitation]) -> dict[str, EvidenceCitation]:
    return {citation.evidence_id: citation for citation in citations}


def source_summary(evidence_ids: list[str] | None, citations: dict[str, EvidenceCitation]) -> str:
    labels = [
        short_citation(citations[evidence_id])
        for evidence_id in normalize_evidence_ids(evidence_ids)
        if evidence_id in citations
    ]
    return "Sources: " + "; ".join(dict.fromkeys(labels)) if labels else ""


def with_sources(text: str, evidence_ids: list[str] | None, citations: dict[str, EvidenceCitation]) -> str:
    summary = source_summary(evidence_ids, citations)
    return f"{text} ({summary})" if summary else text


def short_citation(citation: EvidenceCitation) -> str:
    return f"{citation.doc_title}, p. {citation.page_start}" if citation.page_start else citation.doc_title


def reference_line(index: int, citation: EvidenceCitation) -> str:
    page = ""
    if citation.page_start is not None and citation.page_end not in (None, citation.page_start):
        page = f", pages {citation.page_start}-{citation.page_end}"
    elif citation.page_start is not None:
        page = f", page {citation.page_start}"
    return f"[{index}] {citation.doc_title}{page} ({citation.doc_id}:{citation.chunk_id})"


def item_parts(item: Any, default_ids: list[str] | None = None) -> tuple[str, list[str]]:
    if isinstance(item, dict):
        return compact(item.get("text") or item.get("value")), normalize_evidence_ids(item.get("evidence_ids") or default_ids)
    return compact(getattr(item, "text", item)), normalize_evidence_ids(getattr(item, "evidence_ids", default_ids))


def row_parts(row: Any, default_ids: list[str] | None = None) -> tuple[list[str], list[str]]:
    if isinstance(row, dict):
        return [compact(value, 220) for value in row.get("values", [])], normalize_evidence_ids(row.get("evidence_ids") or default_ids)
    return [compact(value, 220) for value in getattr(row, "values", row)], normalize_evidence_ids(getattr(row, "evidence_ids", default_ids))
