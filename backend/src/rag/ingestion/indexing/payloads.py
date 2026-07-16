"""Qdrant point payload construction for native PDF chunks."""

from __future__ import annotations

from datetime import date
import hashlib
from uuid import NAMESPACE_URL, uuid5

from rag.shared.contracts.clearance import clearance_rank, normalize_clearance_level
from rag.shared.contracts.group_paths import normalize_group_path

from ..chunking import TextChunk
from ..contracts import IngestJobPayload
from .claims import claim_ids_for_chunk, claims_for_chunk
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
    index_generation_id: str | None = None,
) -> list[dict[str, object]]:
    if len(chunks) != len(vectors):
        raise ValueError("chunks and vectors must have the same length")
    if len(chunks) != len(sparse_vectors):
        raise ValueError("chunks and sparse_vectors must have the same length")

    group_path = normalize_group_path(job.group_path)
    acl_group_paths = _acl_group_paths(owner_group_path=group_path, raw_group_paths=job.acl_group_paths)
    clearance_level = normalize_clearance_level(job.clearance_level)
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    title = title_from_path(job.file_path)
    topics = metadata.get("topics", [])
    normalized_topics = _unique([str(item) for item in topics] if isinstance(topics, list) else [])
    llm_topics = metadata.get("llm_topics", [])
    normalized_llm_topics = _unique([str(item) for item in llm_topics] if isinstance(llm_topics, list) else [])
    conflicted = set(conflicted_claim_ids or [])
    is_expired = _is_expired(job.expiry_date)
    indexed_doc_type = _derived_doc_type(metadata) or job.doc_type
    doc_summary = compact_summary(metadata.get("summary"))
    metadata_confidence = metadata.get("metadata_confidence")
    normalized_confidence = metadata_confidence if isinstance(metadata_confidence, dict) else {}
    metadata_flags = metadata.get("metadata_flags")
    normalized_flags = metadata_flags if isinstance(metadata_flags, dict) else {}
    source_deleted = bool(normalized_flags.get("source_deleted"))
    retrieval_status = str(normalized_flags.get("retrieval_status") or "active")
    points: list[dict[str, object]] = []
    for chunk, vector, sparse_vector in zip(chunks, vectors, sparse_vectors):
        chunk_id = f"{job.doc_id}:{chunk.index}"
        chunk_claim_ids = claim_ids_for_chunk(claims or [], chunk_id)
        chunk_claims = claims_for_chunk(claims or [], chunk_id)
        raw_text_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        normalized_text_hash = hashlib.sha256(_normalized_text(chunk.text).encode("utf-8")).hexdigest()
        item_hash = hashlib.sha256(f"{chunk_id}\0{raw_text_hash}".encode("utf-8")).hexdigest()
        point_identity = f"{index_generation_id}:{chunk_id}" if index_generation_id else chunk_id
        generation_payload = (
            {
                "index_generation_id": index_generation_id,
                "generation_item_hash": item_hash,
                "generation_published": False,
            }
            if index_generation_id
            else {}
        )
        points.append(
            {
                "id": str(uuid5(NAMESPACE_URL, point_identity)),
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
                    "acl_group_paths": acl_group_paths,
                    "clearance_level": clearance_level,
                    "clearance_rank": clearance_rank(clearance_level),
                    "doc_type": indexed_doc_type,
                    "effective_date": job.effective_date,
                    "expiry_date": job.expiry_date,
                    "is_current": not bool(index_generation_id),
                    "source_id": f"upload:{content_hash}",
                    "content_hash": content_hash,
                    "chunk_content_hash": raw_text_hash,
                    "text_hash": normalized_text_hash,
                    "page": chunk.page,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "language": str(metadata.get("language", "unknown") or "unknown"),
                    "topics": normalized_topics,
                    "llm_topics": normalized_llm_topics,
                    "doc_summary": doc_summary,
                    "metadata_terms": metadata_terms_for_chunk(title=title, chunk=chunk, metadata=metadata),
                    "metadata_version": metadata_version(metadata),
                    "metadata_confidence": normalized_confidence,
                    "named_entities": _entities_for_chunk(metadata.get("named_entities"), chunk.text),
                    "source_deleted": source_deleted,
                    "retrieval_status": retrieval_status,
                    "generated_doc_type": str(metadata.get("doc_type") or ""),
                    "auto_doc_type": str(metadata.get("auto_doc_type") or ""),
                    "claim_ids": chunk_claim_ids,
                    "claims": chunk_claims,
                    "has_conflict": any(claim_id in conflicted for claim_id in chunk_claim_ids),
                    "is_expired": is_expired,
                    **generation_payload,
                },
            }
        )
    return points


def _normalized_text(text: str) -> str:
    return " ".join(text.lower().split())


def _entities_for_chunk(value: object, text: str, *, limit: int = 20) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    haystack = text.lower()
    entities: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        entity_text = str(item.get("text") or "").strip()
        entity_type = str(item.get("type") or "entity").strip() or "entity"
        if not entity_text or entity_text.lower() not in haystack:
            continue
        key = (entity_text.lower(), entity_type.lower())
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            {
                "text": entity_text,
                "type": entity_type,
                "start": item.get("start"),
                "end": item.get("end"),
            }
        )
        if len(entities) >= limit:
            break
    return entities


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
        if value:
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


def _acl_group_paths(*, owner_group_path: str, raw_group_paths: list[str] | None) -> list[str]:
    candidates = raw_group_paths if raw_group_paths is not None else [owner_group_path]
    normalized = [normalize_group_path(path) for path in candidates]
    if owner_group_path not in normalized:
        normalized.insert(0, owner_group_path)
    ordered = [owner_group_path, *[path for path in normalized if path != owner_group_path]]
    return _unique(ordered)
