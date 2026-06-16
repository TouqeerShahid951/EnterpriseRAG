"""CLI for recreating Qdrant and enqueueing hybrid reindex jobs."""

from __future__ import annotations

import argparse
from typing import Any

from rag.shared.contracts.qdrant_schema import collection_mode, collection_vector_size

from ..core.config import settings
from ..query.http import ServiceRequestError, request_json
from ..services.ingest_queue import CeleryIngestQueue
from .qdrant_document_repair import mark_documents_not_current
from .reindex_jobs import (
    build_ingest_message,
    reindex_document_from_row,
    reindex_documents_query,
    superseded_doc_ids_query,
)


def main() -> None:
    args = _parse_args()
    if args.repair_current_flags:
        _repair_current_flags()
        return
    rows = _fetch_candidate_rows(include_failed=args.include_failed, limit=args.limit, doc_ids=args.doc_id)
    documents = [reindex_document_from_row(row) for row in rows]
    print(f"candidate_documents={len(documents)}")
    if not documents:
        return
    _print_candidates(documents)
    if args.dry_run:
        print("dry_run=true")
        return
    if not args.confirm_delete_qdrant and not args.confirm_requeue_only:
        raise SystemExit("Refusing to mutate without --confirm-delete-qdrant or --confirm-requeue-only.")
    if args.confirm_delete_qdrant:
        _delete_collection_if_present()
    else:
        print("qdrant_delete=skipped")
    queue = CeleryIngestQueue(
        broker_url=settings.celery_broker_url or settings.redis_url,
        queue_name=settings.ingest_queue_name,
        task_name=settings.ingest_task_name,
    )
    for document in documents:
        job_id = _create_reindex_job(document.doc_id)
        queue.enqueue(build_ingest_message(document, job_id))
        print(f"queued doc_id={document.doc_id} job_id={job_id}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-delete-qdrant", action="store_true")
    parser.add_argument("--confirm-requeue-only", action="store_true")
    parser.add_argument("--doc-id", action="append", default=[])
    parser.add_argument("--include-failed", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--repair-current-flags", action="store_true")
    return parser.parse_args()


def _fetch_candidate_rows(
    *,
    include_failed: bool,
    limit: int | None,
    doc_ids: list[str],
) -> list[dict[str, Any]]:
    query, params = reindex_documents_query(include_failed=include_failed, limit=limit, doc_ids=doc_ids)
    with _connect() as conn:
        return list(conn.execute(query, params).fetchall())


def _create_reindex_job(doc_id: str) -> str:
    with _connect() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                INSERT INTO ingest_jobs (doc_id, status, progress_pct)
                VALUES (%s, 'queued', 0)
                RETURNING id::text
                """,
                (doc_id,),
            ).fetchone()
            conn.execute("UPDATE documents SET ingest_status = 'queued', updated_at = NOW() WHERE id = %s", (doc_id,))
            conn.execute(
                """
                INSERT INTO audit_log (event_type, target_type, target_id, payload)
                VALUES ('rag.reindex_queued', 'document', %s, jsonb_build_object('job_id', %s::text))
                """,
                (doc_id, row["id"]),
            )
    return str(row["id"])


def _delete_collection_if_present() -> None:
    path = f"/collections/{settings.qdrant_collection}"
    try:
        payload = request_json(settings.qdrant_url, path, service="qdrant", timeout_seconds=settings.rag_http_timeout_seconds)
    except ServiceRequestError as exc:
        if exc.status_code == 404:
            print("qdrant_collection=missing")
            return
        raise
    size = collection_vector_size(payload)
    print(f"qdrant_collection_mode={collection_mode(payload, size or 0) or 'unknown'} vector_size={size}")
    request_json(settings.qdrant_url, path, service="qdrant", method="DELETE", timeout_seconds=settings.rag_http_timeout_seconds)
    print(f"deleted_qdrant_collection={settings.qdrant_collection}")


def _repair_current_flags() -> None:
    with _connect() as conn:
        doc_ids = [row["doc_id"] for row in conn.execute(superseded_doc_ids_query()).fetchall()]
    updated = mark_documents_not_current(
        qdrant_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        doc_ids=doc_ids,
        timeout_seconds=settings.rag_http_timeout_seconds,
    )
    print(f"repaired_superseded_docs={len(doc_ids)} repaired_points={updated}")


def _connect():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required to plan a reindex") from exc
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def _print_candidates(documents: list[Any]) -> None:
    for document in documents[:10]:
        print(f"candidate doc_id={document.doc_id} group_path={document.group_path} supersedes={len(document.supersedes)}")
    if len(documents) > 10:
        print(f"candidate_preview_truncated={len(documents) - 10}")


if __name__ == "__main__":
    main()
