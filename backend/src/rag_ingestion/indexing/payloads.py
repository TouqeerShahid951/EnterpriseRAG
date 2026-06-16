"""Qdrant point payload construction for native PDF chunks."""

from __future__ import annotations

from datetime import date
import hashlib
from uuid import NAMESPACE_URL, uuid5

from rag.shared.contracts.clearance import clearance_rank, normalize_clearance_level
from rag.shared.contracts.group_paths import normalize_group_path

from ..chunking import TextChunk
from ..messages import IngestJobPayload
from .claims import claim_ids_for_chunk
from .metadata_text import compact_summary, metadata_terms_for_chunk, metadata_version, title_from_path
from .sparse import SparseVector

def build_qdrant_points(
    *,
    job: IngestJobPayload,
    chunks: list[TextChunk],
    vectors: list[list[float]],
    sparse_vectors: list[SparseVector],
    metadata: dict[str, object],
    file_bytes: bytes,
    claims: list[dict[str, str]] | None = None,
    conflicted_claim_ids: list[str] | None = None,
) -> list[dict[str, object]]:
    if len(chunks) != len(vectors):
        raise ValueError("chunks and vectors must have the same length")
    if len(chunks) != len(sparse_vectors):
        raise ValueError("chunks and sparse_vectors must have the same length")

    group_path = normalize_group_path(job.group_path)
    clearance_level = normalize_clearance_level(job.clearance_level)
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    title = title_from_path(job.file_path)
    topics = metadata.get("topics", [])
    normalized_topics = [str(item) for item in topics] if isinstance(topics, list) else []
    llm_topics = metadata.get("llm_topics", [])
    normalized_topics = _unique([*normalized_topics, *([str(item) for item in llm_topics] if isinstance(llm_topics, list) else [])])
    conflicted = set(conflicted_claim_ids or [])
    is_expired = _is_expired(job.expiry_date)
    indexed_doc_type = _derived_doc_type(metadata) or job.doc_type or "other"
    doc_summary = compact_summary(metadata.get("summary"))
    metadata_confidence = metadata.get("metadata_confidence")
    normalized_confidence = metadata_confidence if isinstance(metadata_confidence, dict) else {}
    points: list[dict[str, object]] = []
    for chunk, vector, sparse_vector in zip(chunks, vectors, sparse_vectors):
        chunk_id = f"{job.doc_id}:{chunk.index}"
        chunk_claim_ids = claim_ids_for_chunk(claims or [], chunk_id)
        raw_text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        normalized_text_hash = hashlib.sha256(_normalized_text(chunk.text).encode("utf-8")).hexdigest()
        points.append(
            {
                "id": str(uuid5(NAMESPACE_URL, chunk_id)),
                "vector": {
                    "dense": vector,
                    "sparse": sparse_vector.as_qdrant(),
                },
                "payload": {
                    "doc_id": job.doc_id,
                    "doc_title": title,
                    "chunk_id": chunk_id,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "chunk_type": chunk.chunk_type,
                    "text": chunk.text,
                    "parent_text": chunk.parent_text,
                    "parent_page_start": chunk.parent_page_start,
                    "parent_page_end": chunk.parent_page_end,
                    "section_title": chunk.section_title or "",
                    "section_path": chunk.section_path,
                    "parent_section_id": chunk.parent_section_id or "",
                    "parser": chunk.parser,
                    "quality_flags": chunk.quality_flags,
                    "table_json": chunk.table_json or {},
                    "table_title": chunk.table_title,
                    "table_caption": chunk.table_caption,
                    "table_row_label": chunk.table_row_label,
                    "table_column_headers": chunk.table_column_headers,
                    "table_row_index": chunk.table_row_index,
                    "structured_kind": chunk.structured_kind,
                    "structured_fields": chunk.structured_fields,
                    "structured_field_names": chunk.structured_field_names,
                    "structured_field_values": chunk.structured_field_values,
                    "structured_search_text": chunk.structured_search_text,
                    "source_regions": chunk.source_regions,
                    "group_path": group_path,
                    "acl_group_paths": [group_path],
                    "clearance_level": clearance_level,
                    "clearance_rank": clearance_rank(clearance_level),
                    "doc_type": indexed_doc_type,
                    "effective_date": job.effective_date,
                    "expiry_date": job.expiry_date,
                    "is_current": True,
                    "source_id": f"upload:{content_hash}",
                    "content_hash": content_hash,
                    "chunk_content_hash": raw_text_hash,
                    "text_hash": normalized_text_hash,
                    "page": chunk.page,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "language": str(metadata.get("language", "unknown") or "unknown"),
                    "topics": normalized_topics,
                    "doc_summary": doc_summary,
                    "metadata_terms": metadata_terms_for_chunk(title=title, chunk=chunk, metadata=metadata),
                    "metadata_version": metadata_version(metadata),
                    "metadata_confidence": normalized_confidence,
                    "generated_doc_type": str(metadata.get("doc_type", "other")),
                    "auto_doc_type": str(metadata.get("auto_doc_type", "other")),
                    "claim_ids": chunk_claim_ids,
                    "has_conflict": any(claim_id in conflicted for claim_id in chunk_claim_ids),
                    "is_expired": is_expired,
                },
            }
        )
    return points


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def _is_expired(expiry_date: str | None) -> bool:
    if not expiry_date:
        return False
    try:
        return date.fromisoformat(expiry_date) < date.today()
    except ValueError:
        return False


def _derived_doc_type(metadata: dict[str, object]) -> str | None:
    for key in ("doc_type", "auto_doc_type"):
        value = str(metadata.get(key) or "").strip().lower()
        if value and value != "other":
            return value
    return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = value.strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            normalized.append(text)
    return normalized
