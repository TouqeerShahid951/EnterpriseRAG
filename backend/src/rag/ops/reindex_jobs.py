"""Helpers for planning Qdrant hybrid reindex jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..services.ingest_queue import IngestQueueMessage
from ..shared.contracts.clearance import normalize_clearance_level


@dataclass(frozen=True)
class ReindexDocument:
    doc_id: str
    file_path: str
    group_path: str
    clearance_level: str
    doc_type: str | None
    effective_date: str | None
    expiry_date: str | None
    description: str | None
    supersedes: list[str]


def reindex_documents_query(
    *,
    include_failed: bool,
    limit: int | None,
    doc_ids: list[str] | None = None,
) -> tuple[str, tuple[Any, ...]]:
    status_filter = "" if include_failed else "AND d.ingest_status = 'complete'"
    doc_filter = "AND d.id = ANY(%s::uuid[])" if doc_ids else ""
    limit_clause = "LIMIT %s" if limit is not None else ""
    params = []
    if doc_ids:
        params.append(doc_ids)
    if limit is not None:
        params.append(limit)
    return (
        f"""
        SELECT
            d.id::text AS doc_id,
            d.file_path,
            d.group_path,
            d.clearance_level,
            d.doc_type AS doc_type,
            d.effective_date,
            d.expiry_date,
            d.description,
            COALESCE(
                jsonb_agg(e.old_doc_id::text) FILTER (WHERE e.old_doc_id IS NOT NULL),
                d.pending_supersedes,
                '[]'::jsonb
            ) AS supersedes
        FROM documents d
        LEFT JOIN supersession_edges e ON e.new_doc_id = d.id
        WHERE d.deleted_at IS NULL
          AND d.file_path IS NOT NULL
          {status_filter}
          {doc_filter}
        GROUP BY d.id
        ORDER BY d.created_at ASC, d.id ASC
        {limit_clause}
        """,
        tuple(params),
    )


def superseded_doc_ids_query() -> str:
    return """
        SELECT DISTINCT old_doc_id::text AS doc_id
        FROM supersession_edges
        ORDER BY old_doc_id::text
    """


def reindex_document_from_row(row: dict[str, Any]) -> ReindexDocument:
    return ReindexDocument(
        doc_id=str(row["doc_id"]),
        file_path=str(row["file_path"]),
        group_path=str(row["group_path"]),
        clearance_level=normalize_clearance_level(row.get("clearance_level")),
        doc_type=str(row["doc_type"]) if row.get("doc_type") else None,
        effective_date=_optional_date_string(row.get("effective_date")),
        expiry_date=_optional_date_string(row.get("expiry_date")),
        description=str(row["description"]) if row.get("description") else None,
        supersedes=_coerce_supersedes(row.get("supersedes")),
    )


def build_ingest_message(document: ReindexDocument, job_id: str) -> IngestQueueMessage:
    return IngestQueueMessage(
        job_id=job_id,
        doc_id=document.doc_id,
        file_path=document.file_path,
        group_path=document.group_path,
        clearance_level=document.clearance_level,
        doc_type=document.doc_type,
        effective_date=document.effective_date,
        supersedes=document.supersedes,
        expiry_date=document.expiry_date,
        description=document.description,
    )


def _coerce_supersedes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    raise ValueError("supersedes must be decoded as a list")


def _date_string(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _optional_date_string(value: Any) -> str | None:
    if value is None:
        return None
    return _date_string(value)
