"""PostgreSQL document repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from ..auth.abac import normalize_group_path
from ..shared.contracts.clearance import ClearanceLevel, normalize_clearance_level
from .document_models import (
    AuditEventRecord,
    DocumentCrossReferenceRecord,
    DocumentEntityRecord,
    DocumentImageAssetRecord,
    DocumentRecord,
    ImageReviewBatchRecord,
    ImageReviewCandidateRecord,
    ImageReviewDecisionRecord,
    IngestAttemptResult,
    IngestJobCancellationResult,
    IngestJobMutationResult,
    IngestJobRecord,
    ReviewBatchRecord,
    ReviewDecisionRecord,
    ReviewItemRecord,
)
from .postgres import PostgresConnectionMixin


class PostgresDocumentRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create_document(self, **kwargs: Any) -> DocumentRecord:
        row = self._execute_one(
            """
            INSERT INTO documents (
                id, title, source_id, group_path, clearance_level, doc_type, effective_date, expiry_date, description,
                uploaded_by, file_path, content_hash, pending_supersedes, ingest_status
            )
            VALUES (COALESCE(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING *
            """,
            (
                kwargs.get("document_id"),
                kwargs["title"],
                kwargs["source_id"].strip(),
                normalize_group_path(kwargs["group_path"]),
                normalize_clearance_level(kwargs.get("clearance_level")),
                kwargs["doc_type"],
                kwargs["effective_date"],
                kwargs.get("expiry_date"),
                kwargs.get("description"),
                kwargs["uploaded_by"],
                kwargs["file_path"],
                kwargs["content_hash"],
                json.dumps(kwargs["pending_supersedes"]),
                kwargs["ingest_status"],
            ),
        )
        return document_from_row(row)

    def list_documents(self, *, state: Literal["active", "deleted"] = "active") -> list[DocumentRecord]:
        if state not in {"active", "deleted"}:
            raise ValueError("document state must be active or deleted")
        deleted_clause = "d.deleted_at IS NULL" if state == "active" else "d.deleted_at IS NOT NULL"
        rows = self._execute_all(
            f"""
            SELECT d.*, COALESCE(shares.shared_group_paths, '[]'::jsonb) AS shared_group_paths
            FROM documents d
            LEFT JOIN (
                SELECT document_id, jsonb_agg(group_path ORDER BY group_path) AS shared_group_paths
                FROM document_shares
                GROUP BY document_id
            ) shares ON shares.document_id = d.id
            WHERE {deleted_clause}
            ORDER BY d.created_at DESC
            """
        )
        return [document_from_row(row) for row in rows]

    def get_document(self, document_id: str, *, include_deleted: bool = False) -> DocumentRecord | None:
        deleted_clause = "" if include_deleted else "AND d.deleted_at IS NULL"
        row = self._execute_optional(
            f"""
            SELECT d.*, COALESCE(shares.shared_group_paths, '[]'::jsonb) AS shared_group_paths
            FROM documents d
            LEFT JOIN (
                SELECT document_id, jsonb_agg(group_path ORDER BY group_path) AS shared_group_paths
                FROM document_shares
                GROUP BY document_id
            ) shares ON shares.document_id = d.id
            WHERE d.id = %s {deleted_clause}
            """,
            (document_id,),
        )
        return document_from_row(row) if row else None

    def list_document_shares(self, document_id: str) -> list[str]:
        rows = self._execute_all(
            """
            SELECT group_path
            FROM document_shares
            WHERE document_id = %s
            ORDER BY group_path
            """,
            (document_id,),
        )
        return [str(row["group_path"]) for row in rows]

    def replace_document_shares(
        self,
        document_id: str,
        *,
        group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None:
        normalized = _unique_text([normalize_group_path(path) for path in group_paths])
        with self._connect() as conn:
            with conn.transaction():
                document = conn.execute(
                    "SELECT id::text, group_path FROM documents WHERE id = %s",
                    (document_id,),
                ).fetchone()
                if document is None:
                    return None
                owner_group_path = normalize_group_path(str(document["group_path"]))
                shares = [path for path in normalized if path != owner_group_path]
                conn.execute("DELETE FROM document_shares WHERE document_id = %s", (document_id,))
                for group_path in shares:
                    conn.execute(
                        """
                        INSERT INTO document_shares (document_id, group_path, created_by)
                        VALUES (%s, %s, %s)
                        """,
                        (document_id, group_path, actor_id),
                    )
                conn.execute("UPDATE documents SET updated_at = NOW() WHERE id = %s", (document_id,))
        return self.get_document(document_id, include_deleted=True)

    def replace_document_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        shared_group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None:
        owner_group = normalize_group_path(owner_group_path)
        shares = [path for path in _unique_text([normalize_group_path(path) for path in shared_group_paths]) if path != owner_group]
        with self._connect() as conn:
            with conn.transaction():
                document = conn.execute("SELECT id::text FROM documents WHERE id = %s", (document_id,)).fetchone()
                if document is None:
                    return None
                conn.execute(
                    """
                    UPDATE documents
                    SET group_path = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (owner_group, document_id),
                )
                conn.execute("DELETE FROM document_shares WHERE document_id = %s", (document_id,))
                for group_path in shares:
                    conn.execute(
                        """
                        INSERT INTO document_shares (document_id, group_path, created_by)
                        VALUES (%s, %s, %s)
                        """,
                        (document_id, group_path, actor_id),
                    )
        return self.get_document(document_id, include_deleted=True)

    def remove_document_share(self, document_id: str, group_path: str) -> DocumentRecord | None:
        normalized = normalize_group_path(group_path)
        with self._connect() as conn:
            with conn.transaction():
                document = conn.execute("SELECT id::text FROM documents WHERE id = %s", (document_id,)).fetchone()
                if document is None:
                    return None
                conn.execute(
                    "DELETE FROM document_shares WHERE document_id = %s AND group_path = %s",
                    (document_id, normalized),
                )
                conn.execute("UPDATE documents SET updated_at = NOW() WHERE id = %s", (document_id,))
        return self.get_document(document_id, include_deleted=True)

    def update_document_clearance(self, document_id: str, clearance_level: ClearanceLevel) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents
            SET clearance_level = %s,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (normalize_clearance_level(clearance_level), document_id),
        )
        return document_from_row(row) if row else None

    def update_document_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents
            SET topics = %s::jsonb,
                llm_topics = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (
                json.dumps(_unique_text(topics)),
                json.dumps(_unique_text(llm_topics)),
                document_id,
            ),
        )
        return document_from_row(row) if row else None

    def mark_document_stale(
        self,
        document_id: str,
        *,
        source_deleted: bool = True,
        retrieval_status: str = "stale",
        reason: str = "source_deleted",
    ) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents
            SET metadata_flags = metadata_flags || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (
                json.dumps(
                    {
                        "source_deleted": source_deleted,
                        "retrieval_status": retrieval_status,
                        "stale_reason": reason,
                        "stale_at": datetime.now(UTC).isoformat(),
                    }
                ),
                document_id,
            ),
        )
        return document_from_row(row) if row else None

    def save_document_metadata(
        self,
        *,
        document_id: str,
        summary: str | None,
        language: str | None,
        topics: list[str],
        llm_topics: list[str],
        doc_type: str | None = None,
        auto_doc_type: str | None,
        extracted_dates: dict[str, Any],
        metadata_flags: dict[str, Any],
        entities: list[DocumentEntityRecord],
        cross_references: list[DocumentCrossReferenceRecord],
    ) -> DocumentRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE documents
                    SET summary = %s,
                        language = %s,
                        topics = %s::jsonb,
                        llm_topics = %s::jsonb,
                        doc_type = COALESCE(%s, doc_type),
                        auto_doc_type = %s,
                        extracted_dates = %s::jsonb,
                        metadata_flags = %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s AND deleted_at IS NULL
                    RETURNING *
                    """,
                    (
                        summary,
                        language,
                        json.dumps(_unique_text(topics)),
                        json.dumps(_unique_text(llm_topics)),
                        doc_type,
                        auto_doc_type,
                        json.dumps(extracted_dates),
                        json.dumps(metadata_flags),
                        document_id,
                    ),
                ).fetchone()
                if row is None:
                    return None
                conn.execute("DELETE FROM document_entities WHERE doc_id = %s", (document_id,))
                for entity in entities:
                    conn.execute(
                        """
                        INSERT INTO document_entities (doc_id, text, entity_type, start_offset, end_offset)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (document_id, entity.text, entity.type, entity.start, entity.end),
                    )
                conn.execute("DELETE FROM document_cross_references WHERE doc_id = %s", (document_id,))
                for ref in cross_references:
                    conn.execute(
                        """
                        INSERT INTO document_cross_references (doc_id, ref_text, ref_type, position)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (document_id, ref.ref_text, ref.ref_type, ref.position),
                    )
        return document_from_row(row)

    def list_document_entities(self, document_id: str) -> list[DocumentEntityRecord]:
        rows = self._execute_all(
            """
            SELECT doc_id, text, entity_type, start_offset, end_offset
            FROM document_entities
            WHERE doc_id = %s
            ORDER BY COALESCE(start_offset, 2147483647), lower(text), entity_type
            """,
            (document_id,),
        )
        return [
            DocumentEntityRecord(
                doc_id=str(row["doc_id"]),
                text=str(row["text"]),
                type=str(row["entity_type"]),
                start=row.get("start_offset"),
                end=row.get("end_offset"),
            )
            for row in rows
        ]

    def list_document_cross_references(self, document_id: str) -> list[DocumentCrossReferenceRecord]:
        rows = self._execute_all(
            """
            SELECT doc_id, ref_text, ref_type, position
            FROM document_cross_references
            WHERE doc_id = %s
            ORDER BY COALESCE(position, 2147483647), lower(ref_text), ref_type
            """,
            (document_id,),
        )
        return [
            DocumentCrossReferenceRecord(
                doc_id=str(row["doc_id"]),
                ref_text=str(row["ref_text"]),
                ref_type=str(row["ref_type"]),
                position=row.get("position"),
            )
            for row in rows
        ]

    def find_current_by_content_hash(self, content_hash: str) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            SELECT * FROM documents
            WHERE content_hash = %s AND deleted_at IS NULL AND is_current = TRUE
            ORDER BY created_at DESC LIMIT 1
            """,
            (content_hash,),
        )
        return document_from_row(row) if row else None

    def soft_delete_document(self, document_id: str) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents
            SET deleted_at = COALESCE(deleted_at, NOW()), is_current = FALSE, updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL RETURNING *
            """,
            (document_id,),
        )
        return document_from_row(row) if row else None

    def restore_document(self, document_id: str) -> DocumentRecord | None:
        row = self._execute_optional(
            """
            UPDATE documents d
            SET deleted_at = NULL,
                is_current = NOT EXISTS (
                    SELECT 1 FROM supersession_edges e WHERE e.old_doc_id = d.id
                ),
                updated_at = NOW()
            WHERE d.id = %s AND d.deleted_at IS NOT NULL
            RETURNING *
            """,
            (document_id,),
        )
        return document_from_row(row) if row else None

    def permanently_delete_document(self, document_id: str) -> DocumentRecord | None:
        row = self._execute_optional(
            "DELETE FROM documents WHERE id = %s RETURNING *",
            (document_id,),
        )
        return document_from_row(row) if row else None

    def create_ingest_job(
        self,
        *,
        doc_id: str,
        status: str,
        progress_pct: int,
        origin: str = "unknown",
        retry_of_job_id: str | None = None,
    ) -> IngestJobRecord:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO ingest_jobs (doc_id, retry_of_job_id, origin, status, progress_pct, completed_at)
                    VALUES (%s, %s, %s, %s, %s, CASE WHEN %s IN ('complete', 'failed', 'human_review', 'cancelled') THEN NOW() END)
                    RETURNING *
                    """,
                    (doc_id, retry_of_job_id, origin, status, progress_pct, status),
                ).fetchone()
                conn.execute("UPDATE documents SET ingest_status = %s, updated_at = NOW() WHERE id = %s", (status, doc_id))
        return job_from_row(row)

    def get_ingest_job(self, job_id: str) -> IngestJobRecord | None:
        row = self._execute_optional("SELECT * FROM ingest_jobs WHERE id = %s", (job_id,))
        return job_from_row(row) if row else None

    def list_ingest_jobs(self) -> list[IngestJobRecord]:
        rows = self._execute_all("SELECT * FROM ingest_jobs ORDER BY created_at DESC, id DESC")
        return [job_from_row(row) for row in rows]

    def get_active_ingest_job_for_document(self, doc_id: str) -> IngestJobRecord | None:
        row = self._execute_optional(
            """
            SELECT * FROM ingest_jobs
            WHERE doc_id = %s
              AND status IN ('scheduled', 'queued', 'processing', 'human_review')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (doc_id,),
        )
        return job_from_row(row) if row else None

    def update_ingest_job(
        self,
        job_id: str,
        *,
        status: str,
        progress_pct: int,
        stage_progress: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
        expected_statuses: frozenset[str] | None = None,
        stale_before: datetime | None = None,
        run_token: str | None = None,
    ) -> IngestJobMutationResult:
        with self._connect() as conn:
            with conn.transaction():
                current_row = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if current_row is None:
                    return IngestJobMutationResult(job=None, changed=False)
                current = job_from_row(current_row)
                if current.status == "cancelled" and status != "cancelled":
                    return IngestJobMutationResult(job=current, changed=False)
                if expected_statuses is not None and current.status not in expected_statuses:
                    return IngestJobMutationResult(job=current, changed=False)
                last_activity = (
                    current.last_heartbeat_at or current.updated_at or current.created_at
                )
                if (
                    stale_before is not None
                    and last_activity is not None
                    and last_activity >= stale_before
                ):
                    return IngestJobMutationResult(job=current, changed=False)
                if not _run_token_can_update(
                    current,
                    run_token=run_token,
                    next_status=status,
                ):
                    return IngestJobMutationResult(job=current, changed=False)
                next_run_token = _next_run_token(
                    current,
                    run_token=run_token,
                    next_status=status,
                )
                progress_is_stale = (
                    current.status == "processing"
                    and status == "processing"
                    and progress_pct < current.progress_pct
                )
                next_progress_pct = (
                    max(current.progress_pct, progress_pct)
                    if current.status == "processing" and status == "processing"
                    else progress_pct
                )
                next_stage_progress = (
                    current.stage_progress if progress_is_stale else stage_progress
                )
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = %s,
                        progress_pct = %s,
                        stage_progress = %s::jsonb,
                        warnings = COALESCE(%s::jsonb, warnings),
                        error_code = %s,
                        error_message_safe = %s,
                        run_token = %s,
                        updated_at = NOW(),
                        completed_at = CASE
                            WHEN %s IN ('complete', 'failed', 'human_review', 'cancelled') THEN NOW()
                        END
                    WHERE id = %s AND status = %s
                    RETURNING *
                    """,
                    (
                        status,
                        next_progress_pct,
                        json.dumps(next_stage_progress)
                        if next_stage_progress is not None
                        else None,
                        json.dumps(warnings) if warnings is not None else None,
                        error_code,
                        error_message_safe,
                        next_run_token,
                        status,
                        job_id,
                        current.status,
                    ),
                ).fetchone()
                updated_row = _require_row(row, "locked ingestion job update")
                conn.execute(
                    "UPDATE documents SET ingest_status = %s, updated_at = NOW() WHERE id = %s",
                    (status, updated_row["doc_id"]),
                )
        return IngestJobMutationResult(job=job_from_row(updated_row), changed=True)

    def requeue_stale_ingest_job(
        self,
        job_id: str,
        *,
        stale_before: datetime,
        max_attempts: int,
    ) -> IngestJobRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = 'queued',
                        progress_pct = 0,
                        error_code = NULL,
                        error_message_safe = NULL,
                        run_token = NULL,
                        completed_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                      AND status = 'processing'
                      AND COALESCE(last_heartbeat_at, updated_at, created_at) < %s
                      AND attempt_count < %s
                    RETURNING *
                    """,
                    (job_id, stale_before, max_attempts),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE documents SET ingest_status = 'queued', updated_at = NOW() WHERE id = %s",
                        (row["doc_id"],),
                    )
        return job_from_row(row) if row else None

    def start_ingest_attempt(
        self,
        job_id: str,
        *,
        max_attempts: int,
        stale_after_seconds: int = 120,
        run_token: str | None = None,
    ) -> IngestAttemptResult:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = 'processing',
                        attempt_count = attempt_count + 1,
                        last_heartbeat_at = NOW(),
                        run_token = %s,
                        error_code = NULL,
                        error_message_safe = NULL,
                        completed_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                      AND (
                          status = 'queued'
                          OR (
                              status = 'processing'
                              AND (run_token IS DISTINCT FROM %s OR %s::text IS NULL)
                              AND COALESCE(last_heartbeat_at, updated_at, created_at)
                                  < NOW() - (%s * INTERVAL '1 second')
                          )
                      )
                      AND attempt_count < %s
                    RETURNING *
                    """,
                    (
                        run_token,
                        job_id,
                        run_token,
                        run_token,
                        stale_after_seconds,
                        max_attempts,
                    ),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE documents SET ingest_status = 'processing', updated_at = NOW() WHERE id = %s",
                        (row["doc_id"],),
                    )
                    return IngestAttemptResult(job=job_from_row(row), claimed=True)
                current = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s",
                    (job_id,),
                ).fetchone()
                if (
                    run_token is not None
                    and current is not None
                    and current.get("status") == "processing"
                    and current.get("run_token") == run_token
                ):
                    return IngestAttemptResult(
                        job=job_from_row(current),
                        claimed=True,
                    )
        return IngestAttemptResult(
            job=job_from_row(current) if current else None,
            claimed=False,
        )

    def heartbeat_ingest_job(
        self,
        job_id: str,
        *,
        run_token: str | None = None,
    ) -> IngestJobMutationResult:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET last_heartbeat_at = NOW()
                    WHERE id = %s
                      AND status = 'processing'
                      AND run_token IS NOT DISTINCT FROM %s
                    RETURNING *
                    """,
                    (job_id, run_token),
                ).fetchone()
                if row:
                    return IngestJobMutationResult(job=job_from_row(row), changed=True)
                current = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s",
                    (job_id,),
                ).fetchone()
        return IngestJobMutationResult(
            job=job_from_row(current) if current else None,
            changed=False,
        )

    def record_ingest_parser_provenance(
        self,
        job_id: str,
        *,
        provenance: dict[str, Any],
        run_token: str | None = None,
    ) -> IngestJobRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET parser_provenance = %s::jsonb, updated_at = NOW()
                    WHERE id = %s
                      AND status = 'processing'
                      AND run_token IS NOT DISTINCT FROM %s
                    RETURNING *
                    """,
                    (json.dumps(provenance), job_id, run_token),
                ).fetchone()
                if row:
                    conn.execute(
                        """
                        INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
                        VALUES ('internal.ingest.parser_provenance', NULL, 'ingest_job', %s, %s::jsonb)
                        """,
                        (
                            row["id"],
                            json.dumps({"doc_id": str(row["doc_id"]), "provenance": provenance}),
                        ),
                    )
        return job_from_row(row) if row else None

    def cancel_ingest_job(
        self,
        job_id: str,
        *,
        allowed_statuses: frozenset[str],
    ) -> IngestJobCancellationResult:
        with self._connect() as conn:
            with conn.transaction():
                current_row = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if current_row is None:
                    return IngestJobCancellationResult(
                        job=None,
                        changed=False,
                        review_items_closed=0,
                    )
                current = job_from_row(current_row)
                if current.status not in allowed_statuses:
                    return IngestJobCancellationResult(
                        job=current,
                        changed=False,
                        review_items_closed=0,
                    )
                review_items_closed = _close_pending_review_items(conn, job_id)
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = 'cancelled',
                        stage_progress = NULL,
                        error_code = NULL,
                        error_message_safe = NULL,
                        run_token = NULL,
                        updated_at = NOW(),
                        completed_at = NOW()
                    WHERE id = %s AND status = %s
                    RETURNING *
                    """,
                    (job_id, current.status),
                ).fetchone()
                updated_row = _require_row(row, "locked ingestion job cancellation")
                conn.execute(
                    "UPDATE documents SET ingest_status = 'cancelled', updated_at = NOW() WHERE id = %s",
                    (updated_row["doc_id"],),
                )
        return IngestJobCancellationResult(
            job=job_from_row(updated_row),
            changed=True,
            review_items_closed=review_items_closed,
        )

    def cancel_review_batch_for_job(self, job_id: str) -> int:
        with self._connect() as conn:
            with conn.transaction():
                return _close_pending_review_items(conn, job_id)

    def mark_superseded(self, *, new_doc_id: str, old_doc_ids: list[str]) -> list[DocumentRecord]:
        with self._connect() as conn:
            with conn.transaction():
                validate_edges(conn, new_doc_id, old_doc_ids)
                rows = []
                for old_doc_id in old_doc_ids:
                    conn.execute("INSERT INTO supersession_edges (old_doc_id, new_doc_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (old_doc_id, new_doc_id))
                    rows.append(conn.execute(
                        "UPDATE documents SET is_current = FALSE, superseded_by = %s, updated_at = NOW() WHERE id = %s RETURNING *",
                        (new_doc_id, old_doc_id),
                    ).fetchone())
        return [document_from_row(row) for row in rows if row]

    def list_version_chain(self, document_id: str) -> list[DocumentRecord]:
        rows = self._execute_all(
            """
            WITH RECURSIVE related(id) AS (
                VALUES (%s::uuid)
                UNION
                SELECT CASE
                    WHEN edge.old_doc_id = related.id THEN edge.new_doc_id
                    ELSE edge.old_doc_id
                END
                FROM related
                JOIN supersession_edges edge
                    ON edge.old_doc_id = related.id OR edge.new_doc_id = related.id
            )
            SELECT * FROM documents WHERE id IN (SELECT id FROM related)
            ORDER BY COALESCE(effective_date, DATE '0001-01-01'), id
            """,
            (document_id,),
        )
        return [document_from_row(row) for row in rows]

    def list_superseded_document_ids(self, document_id: str) -> list[str]:
        rows = self._execute_all(
            """
            SELECT old_doc_id::text AS doc_id
            FROM supersession_edges
            WHERE new_doc_id = %s
            ORDER BY old_doc_id::text
            """,
            (document_id,),
        )
        return [str(row["doc_id"]) for row in rows]

    def append_audit_event(self, **kwargs: Any) -> None:
        self._execute_one(
            """
            INSERT INTO audit_log (event_type, actor_id, target_type, target_id, payload)
            VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id
            """,
            (
                kwargs["event_type"],
                kwargs["actor_id"],
                kwargs["target_type"],
                kwargs["target_id"],
                json.dumps(kwargs["payload"]),
            ),
        )

    def list_audit_events(self, *, limit: int = 100) -> list[AuditEventRecord]:
        rows = self._execute_all(
            """
            SELECT id::text, event_type, actor_id::text, target_type, target_id::text, payload, created_at
            FROM audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (max(1, min(limit, 5000)),),
        )
        return [audit_event_from_row(row) for row in rows]

    def create_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        review_items: list[dict[str, Any]],
    ) -> ReviewBatchRecord:
        with self._connect() as conn:
            with conn.transaction():
                batch_row = conn.execute(
                    """
                    INSERT INTO human_review_batches (job_id, doc_id, parsed_items, resume_payload, status)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, 'pending')
                    RETURNING *
                    """,
                    (job_id, doc_id, json.dumps(parsed_items), json.dumps(resume_payload)),
                ).fetchone()
                for item in review_items:
                    conn.execute(
                        """
                        INSERT INTO human_review_queue (
                            batch_id, doc_id, item_index, item_type, page_start, page_end,
                            bbox, quality_flags, partial_text, confidence, status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, 'pending')
                        """,
                        (
                            batch_row["id"],
                            doc_id,
                            item["item_index"],
                            item.get("item_type") or "text",
                            item.get("page_start"),
                            item.get("page_end"),
                            json.dumps(item.get("bbox")),
                            json.dumps(item.get("quality_flags") or []),
                            item.get("partial_text") or "",
                            item.get("confidence"),
                        ),
                    )
        return review_batch_from_row(batch_row)

    def get_review_batch(self, batch_id: str) -> ReviewBatchRecord | None:
        row = self._execute_optional("SELECT * FROM human_review_batches WHERE id = %s", (batch_id,))
        return review_batch_from_row(row) if row else None

    def list_review_items(self, *, status: str = "pending") -> list[ReviewItemRecord]:
        rows = self._execute_all(
            """
            SELECT q.*, COALESCE(d.title, d.id::text) AS doc_title
            FROM human_review_queue q
            JOIN documents d ON d.id = q.doc_id
            WHERE q.status = %s AND q.batch_id IS NOT NULL AND d.deleted_at IS NULL
            ORDER BY q.created_at ASC, q.item_index ASC, q.id ASC
            """,
            (status,),
        )
        return [review_item_from_row(row) for row in rows]

    def list_review_items_for_batch(self, batch_id: str) -> list[ReviewItemRecord]:
        rows = self._execute_all(
            """
            SELECT q.*, COALESCE(d.title, d.id::text) AS doc_title
            FROM human_review_queue q
            JOIN documents d ON d.id = q.doc_id
            WHERE q.batch_id = %s
            ORDER BY q.item_index ASC, q.id ASC
            """,
            (batch_id,),
        )
        return [review_item_from_row(row) for row in rows]

    def approve_review_item(self, item_id: str, *, corrected_text: str, reviewer_id: str) -> ReviewDecisionRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                item_row = conn.execute(
                    """
                    UPDATE human_review_queue
                    SET status = 'approved',
                        corrected_text = %s,
                        assigned_to = %s,
                        updated_at = NOW()
                    WHERE id = %s AND status = 'pending'
                    RETURNING *
                    """,
                    (corrected_text, reviewer_id, item_id),
                ).fetchone()
                if item_row is None:
                    item_row = conn.execute("SELECT * FROM human_review_queue WHERE id = %s", (item_id,)).fetchone()
                    if item_row is None:
                        return None
                complete = conn.execute(
                    """
                    SELECT NOT EXISTS (
                        SELECT 1 FROM human_review_queue
                        WHERE batch_id = %s AND status <> 'approved'
                    ) AS complete
                    """,
                    (item_row["batch_id"],),
                ).fetchone()["complete"]
                if complete:
                    batch_row = conn.execute(
                        """
                        UPDATE human_review_batches
                        SET status = 'approved', updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (item_row["batch_id"],),
                    ).fetchone()
                else:
                    batch_row = conn.execute("SELECT * FROM human_review_batches WHERE id = %s", (item_row["batch_id"],)).fetchone()
                item_detail = conn.execute(
                    """
                    SELECT q.*, COALESCE(d.title, d.id::text) AS doc_title
                    FROM human_review_queue q
                    JOIN documents d ON d.id = q.doc_id
                    WHERE q.id = %s
                    """,
                    (item_row["id"],),
                ).fetchone()
        return ReviewDecisionRecord(item=review_item_from_row(item_detail), batch=review_batch_from_row(batch_row), batch_complete=bool(complete))

    def reject_review_item(self, item_id: str, *, reviewer_id: str) -> ReviewDecisionRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                item_row = conn.execute(
                    """
                    UPDATE human_review_queue
                    SET status = 'rejected',
                        assigned_to = %s,
                        updated_at = NOW()
                    WHERE id = %s AND status = 'pending'
                    RETURNING *
                    """,
                    (reviewer_id, item_id),
                ).fetchone()
                if item_row is None:
                    item_row = conn.execute("SELECT * FROM human_review_queue WHERE id = %s", (item_id,)).fetchone()
                    if item_row is None:
                        return None
                batch_row = conn.execute(
                    """
                    UPDATE human_review_batches
                    SET status = 'rejected', updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (item_row["batch_id"],),
                ).fetchone()
                item_detail = conn.execute(
                    """
                    SELECT q.*, COALESCE(d.title, d.id::text) AS doc_title
                    FROM human_review_queue q
                    JOIN documents d ON d.id = q.doc_id
                    WHERE q.id = %s
                    """,
                    (item_row["id"],),
                ).fetchone()
        return ReviewDecisionRecord(item=review_item_from_row(item_detail), batch=review_batch_from_row(batch_row), batch_complete=False)

    def create_image_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> ImageReviewBatchRecord:
        with self._connect() as conn:
            with conn.transaction():
                batch_row = conn.execute(
                    """
                    INSERT INTO image_review_batches (
                        job_id, doc_id, parsed_items, resume_payload, status, candidate_count, recommended_count
                    )
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, 'pending', %s, %s)
                    RETURNING *
                    """,
                    (
                        job_id,
                        doc_id,
                        json.dumps(parsed_items),
                        json.dumps(resume_payload),
                        len(candidates),
                        sum(1 for candidate in candidates if bool(candidate.get("recommended", True))),
                    ),
                ).fetchone()
                for candidate in candidates:
                    conn.execute(
                        """
                        INSERT INTO image_review_candidates (
                            batch_id, doc_id, candidate_key, filename, source_kind, page, bbox, page_area_ratio,
                            object_path, content_type, width, height, content_hash, quality_flags, score,
                            recommended, status
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                            %s, %s, %s, %s, %s, %s::jsonb, %s,
                            %s, 'pending'
                        )
                        """,
                        (
                            batch_row["id"],
                            doc_id,
                            candidate["candidate_key"],
                            candidate.get("filename") or "image",
                            candidate.get("source_kind") or "pdf_image",
                            candidate.get("page"),
                            json.dumps(candidate.get("bbox")),
                            candidate.get("page_area_ratio"),
                            candidate["object_path"],
                            candidate.get("content_type") or "image/png",
                            candidate.get("width"),
                            candidate.get("height"),
                            candidate["content_hash"],
                            json.dumps(candidate.get("quality_flags") or []),
                            int(candidate.get("score") or 0),
                            bool(candidate.get("recommended", True)),
                        ),
                    )
                detail = conn.execute(
                    """
                    SELECT b.*, COALESCE(d.title, d.id::text) AS doc_title
                    FROM image_review_batches b
                    JOIN documents d ON d.id = b.doc_id
                    WHERE b.id = %s
                    """,
                    (batch_row["id"],),
                ).fetchone()
        return image_review_batch_from_row(detail)

    def get_image_review_batch(self, batch_id: str) -> ImageReviewBatchRecord | None:
        row = self._execute_optional(
            """
            SELECT b.*, COALESCE(d.title, d.id::text) AS doc_title
            FROM image_review_batches b
            JOIN documents d ON d.id = b.doc_id
            WHERE b.id = %s
            """,
            (batch_id,),
        )
        return image_review_batch_from_row(row) if row else None

    def list_image_review_batches(self, *, status: str = "pending") -> list[ImageReviewBatchRecord]:
        rows = self._execute_all(
            """
            SELECT b.*, COALESCE(d.title, d.id::text) AS doc_title
            FROM image_review_batches b
            JOIN documents d ON d.id = b.doc_id
            WHERE b.status = %s AND d.deleted_at IS NULL
            ORDER BY b.created_at ASC, b.id ASC
            """,
            (status,),
        )
        return [image_review_batch_from_row(row) for row in rows]

    def list_image_review_candidates_for_batch(
        self,
        batch_id: str,
        *,
        status: str | None = None,
    ) -> list[ImageReviewCandidateRecord]:
        status_clause = "AND c.status = %s" if status is not None else ""
        params: tuple[Any, ...] = (batch_id, status) if status is not None else (batch_id,)
        rows = self._execute_all(
            f"""
            SELECT c.*, COALESCE(d.title, d.id::text) AS doc_title
            FROM image_review_candidates c
            JOIN documents d ON d.id = c.doc_id
            WHERE c.batch_id = %s {status_clause}
            ORDER BY COALESCE(c.page, 0), c.score DESC, c.filename, c.id
            """,
            params,
        )
        return [image_review_candidate_from_row(row) for row in rows]

    def get_image_review_candidate(self, candidate_id: str) -> ImageReviewCandidateRecord | None:
        row = self._execute_optional(
            """
            SELECT c.*, COALESCE(d.title, d.id::text) AS doc_title
            FROM image_review_candidates c
            JOIN documents d ON d.id = c.doc_id
            WHERE c.id = %s
            """,
            (candidate_id,),
        )
        return image_review_candidate_from_row(row) if row else None

    def apply_image_review_decisions(
        self,
        batch_id: str,
        *,
        approve_candidate_ids: list[str],
        skip_candidate_ids: list[str],
        reviewer_id: str,
        approve_recommended: bool = False,
        skip_remaining: bool = False,
    ) -> ImageReviewDecisionRecord | None:
        with self._connect() as conn:
            with conn.transaction():
                exists = conn.execute("SELECT 1 FROM image_review_batches WHERE id = %s FOR UPDATE", (batch_id,)).fetchone()
                if exists is None:
                    return None
                changed_ids: set[str] = set()
                if approve_candidate_ids:
                    rows = conn.execute(
                        """
                        UPDATE image_review_candidates
                        SET status = 'approved',
                            assigned_to = %s,
                            skip_reason = NULL,
                            updated_at = NOW()
                        WHERE batch_id = %s AND status = 'pending' AND id = ANY(%s::uuid[])
                        RETURNING id::text
                        """,
                        (reviewer_id, batch_id, approve_candidate_ids),
                    ).fetchall()
                    changed_ids.update(str(row["id"]) for row in rows)
                if approve_recommended:
                    rows = conn.execute(
                        """
                        UPDATE image_review_candidates
                        SET status = 'approved',
                            assigned_to = %s,
                            skip_reason = NULL,
                            updated_at = NOW()
                        WHERE batch_id = %s AND status = 'pending' AND recommended = TRUE
                        RETURNING id::text
                        """,
                        (reviewer_id, batch_id),
                    ).fetchall()
                    changed_ids.update(str(row["id"]) for row in rows)
                if skip_candidate_ids:
                    rows = conn.execute(
                        """
                        UPDATE image_review_candidates
                        SET status = 'skipped',
                            assigned_to = %s,
                            skip_reason = 'reviewer_skipped',
                            updated_at = NOW()
                        WHERE batch_id = %s AND status = 'pending' AND id = ANY(%s::uuid[])
                        RETURNING id::text
                        """,
                        (reviewer_id, batch_id, skip_candidate_ids),
                    ).fetchall()
                    changed_ids.update(str(row["id"]) for row in rows)
                if skip_remaining:
                    rows = conn.execute(
                        """
                        UPDATE image_review_candidates
                        SET status = 'skipped',
                            assigned_to = %s,
                            skip_reason = 'reviewer_skipped',
                            updated_at = NOW()
                        WHERE batch_id = %s AND status = 'pending'
                        RETURNING id::text
                        """,
                        (reviewer_id, batch_id),
                    ).fetchall()
                    changed_ids.update(str(row["id"]) for row in rows)
                complete = conn.execute(
                    """
                    SELECT NOT EXISTS (
                        SELECT 1 FROM image_review_candidates
                        WHERE batch_id = %s AND status = 'pending'
                    ) AS complete
                    """,
                    (batch_id,),
                ).fetchone()["complete"]
                if complete:
                    conn.execute(
                        """
                        UPDATE image_review_batches
                        SET status = 'approved', updated_at = NOW()
                        WHERE id = %s
                        """,
                        (batch_id,),
                    )
                else:
                    conn.execute("UPDATE image_review_batches SET updated_at = NOW() WHERE id = %s", (batch_id,))
                batch_row = conn.execute(
                    """
                    SELECT b.*, COALESCE(d.title, d.id::text) AS doc_title
                    FROM image_review_batches b
                    JOIN documents d ON d.id = b.doc_id
                    WHERE b.id = %s
                    """,
                    (batch_id,),
                ).fetchone()
                candidate_rows = []
                if changed_ids:
                    candidate_rows = conn.execute(
                        """
                        SELECT c.*, COALESCE(d.title, d.id::text) AS doc_title
                        FROM image_review_candidates c
                        JOIN documents d ON d.id = c.doc_id
                        WHERE c.id = ANY(%s::uuid[])
                        ORDER BY COALESCE(c.page, 0), c.score DESC, c.filename, c.id
                        """,
                        (list(changed_ids),),
                    ).fetchall()
        return ImageReviewDecisionRecord(
            batch=image_review_batch_from_row(batch_row),
            candidates=tuple(image_review_candidate_from_row(row) for row in candidate_rows),
            batch_complete=bool(complete),
        )

    def get_image_review_approved_keys(self, batch_id: str) -> list[str]:
        rows = self._execute_all(
            """
            SELECT candidate_key
            FROM image_review_candidates
            WHERE batch_id = %s AND status = 'approved'
            ORDER BY COALESCE(page, 0), score DESC, filename, id
            """,
            (batch_id,),
        )
        return [str(row["candidate_key"]) for row in rows]

    def replace_document_image_assets(
        self,
        *,
        doc_id: str,
        job_id: str,
        assets: list[dict[str, Any]],
    ) -> list[DocumentImageAssetRecord]:
        with self._connect() as conn:
            with conn.transaction():
                exists = conn.execute("SELECT 1 FROM documents WHERE id = %s AND deleted_at IS NULL", (doc_id,)).fetchone()
                if not exists:
                    raise ValueError("document does not exist")
                conn.execute("DELETE FROM document_image_assets WHERE doc_id = %s", (doc_id,))
                rows = []
                for asset in assets:
                    rows.append(
                        conn.execute(
                            """
                            INSERT INTO document_image_assets (
                                id, doc_id, job_id, source_kind, page, bbox, object_path, content_type,
                                width, height, content_hash, extracted_text, caption, confidence, quality_flags
                            )
                            VALUES (
                                COALESCE(%s::uuid, gen_random_uuid()), %s, %s, %s, %s, %s::jsonb,
                                %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                            )
                            RETURNING *
                            """,
                            (
                                asset.get("id"),
                                doc_id,
                                job_id,
                                asset.get("source_kind") or "image",
                                asset.get("page"),
                                json.dumps(asset.get("bbox")),
                                asset["object_path"],
                                asset.get("content_type") or "image/jpeg",
                                asset.get("width"),
                                asset.get("height"),
                                asset["content_hash"],
                                asset.get("extracted_text"),
                                asset.get("caption"),
                                asset.get("confidence"),
                                json.dumps(asset.get("quality_flags") or []),
                            ),
                        ).fetchone()
                    )
        return [image_asset_from_row(row) for row in rows if row]

    def list_document_image_assets(self, document_id: str) -> list[DocumentImageAssetRecord]:
        rows = self._execute_all(
            """
            SELECT *
            FROM document_image_assets
            WHERE doc_id = %s
            ORDER BY COALESCE(page, 0), created_at, id
            """,
            (document_id,),
        )
        return [image_asset_from_row(row) for row in rows]

    def get_document_image_asset(self, document_id: str, asset_id: str) -> DocumentImageAssetRecord | None:
        row = self._execute_optional(
            """
            SELECT *
            FROM document_image_assets
            WHERE doc_id = %s AND id = %s
            """,
            (document_id, asset_id),
        )
        return image_asset_from_row(row) if row else None


def validate_edges(conn: Any, new_doc_id: str, old_doc_ids: list[str]) -> None:
    if len(set(old_doc_ids)) != len(old_doc_ids):
        raise ValueError("supersedes contains duplicate document ids")
    for old_doc_id in old_doc_ids:
        _validate_edge(conn, new_doc_id, old_doc_id)


def _close_pending_review_items(conn: Any, job_id: str) -> int:
    item_rows = conn.execute(
        """
        UPDATE human_review_queue
        SET status = 'rejected', updated_at = NOW()
        WHERE status = 'pending'
          AND batch_id IN (
              SELECT id FROM human_review_batches WHERE job_id = %s
          )
        RETURNING id
        """,
        (job_id,),
    ).fetchall()
    conn.execute(
        """
        UPDATE human_review_batches
        SET status = 'rejected', updated_at = NOW()
        WHERE job_id = %s AND status = 'pending'
        """,
        (job_id,),
    )
    image_rows = conn.execute(
        """
        UPDATE image_review_candidates
        SET status = 'skipped',
            assigned_to = NULL,
            skip_reason = 'ingest_cancelled',
            updated_at = NOW()
        WHERE status = 'pending'
          AND batch_id IN (
              SELECT id FROM image_review_batches WHERE job_id = %s
          )
        RETURNING id
        """,
        (job_id,),
    ).fetchall()
    conn.execute(
        """
        UPDATE image_review_batches
        SET status = 'rejected', updated_at = NOW()
        WHERE job_id = %s AND status = 'pending'
        """,
        (job_id,),
    )
    return len(item_rows) + len(image_rows)


def _require_row(row: dict[str, Any] | None, operation: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"{operation} unexpectedly returned no row")
    return row


def _run_token_can_update(
    current: IngestJobRecord,
    *,
    run_token: str | None,
    next_status: str,
) -> bool:
    if current.run_token is not None:
        return current.run_token == run_token
    if run_token is None:
        return True
    return current.status == "queued" and next_status == "processing"


def _next_run_token(
    current: IngestJobRecord,
    *,
    run_token: str | None,
    next_status: str,
) -> str | None:
    if next_status != "processing":
        return None
    if current.run_token is None and run_token is not None:
        return run_token
    return current.run_token


def document_from_row(row: dict[str, Any]) -> DocumentRecord:
    pending = row.get("pending_supersedes") or []
    shared = tuple(str(value) for value in _json_list(row.get("shared_group_paths")))
    return DocumentRecord(
        id=str(row["id"]),
        title=row.get("title"),
        source_id=row["source_id"],
        group_path=row["group_path"],
        clearance_level=normalize_clearance_level(row.get("clearance_level")),
        doc_type=row.get("doc_type"),
        language=row.get("language"),
        effective_date=row.get("effective_date"),
        expiry_date=row.get("expiry_date"),
        description=row.get("description"),
        summary=row.get("summary"),
        topics=tuple(str(value) for value in _json_list(row.get("topics"))),
        llm_topics=tuple(str(value) for value in _json_list(row.get("llm_topics"))),
        auto_doc_type=row.get("auto_doc_type"),
        extracted_dates=_json_object(row.get("extracted_dates")),
        metadata_flags=_json_object(row.get("metadata_flags")),
        is_current=bool(row["is_current"]),
        superseded_by=str(row["superseded_by"]) if row.get("superseded_by") else None,
        pending_supersedes=tuple(str(value) for value in pending),
        content_hash=row.get("content_hash"),
        uploaded_by=str(row["uploaded_by"]) if row.get("uploaded_by") else None,
        file_path=row.get("file_path"),
        ingest_status=row["ingest_status"],
        deleted_at=row.get("deleted_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        shared_group_paths=shared,
    )


def audit_event_from_row(row: dict[str, Any]) -> AuditEventRecord:
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    return AuditEventRecord(
        id=str(row["id"]),
        event_type=str(row["event_type"]),
        actor_id=str(row["actor_id"]) if row.get("actor_id") is not None else None,
        target_type=str(row["target_type"]) if row.get("target_type") is not None else None,
        target_id=str(row["target_id"]) if row.get("target_id") is not None else None,
        payload=dict(payload),
        created_at=row.get("created_at"),
    )


def job_from_row(row: dict[str, Any]) -> IngestJobRecord:
    return IngestJobRecord(
        id=str(row["id"]),
        doc_id=str(row["doc_id"]),
        retry_of_job_id=str(row["retry_of_job_id"]) if row.get("retry_of_job_id") else None,
        origin=str(row.get("origin") or "unknown"),
        status=row["status"],
        progress_pct=int(row["progress_pct"]),
        stage_progress=_json_object(row.get("stage_progress")) if row.get("stage_progress") is not None else None,
        attempt_count=int(row.get("attempt_count") or 0),
        last_heartbeat_at=row.get("last_heartbeat_at"),
        run_token=str(row["run_token"]) if row.get("run_token") else None,
        warnings=tuple(str(value) for value in _json_list(row.get("warnings"))),
        parser_provenance=_json_object(row.get("parser_provenance")) if row.get("parser_provenance") is not None else None,
        error_code=row.get("error_code"),
        error_message_safe=row.get("error_message_safe"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        completed_at=row.get("completed_at"),
    )


def review_batch_from_row(row: dict[str, Any]) -> ReviewBatchRecord:
    return ReviewBatchRecord(
        id=str(row["id"]),
        job_id=str(row["job_id"]),
        doc_id=str(row["doc_id"]),
        status=str(row["status"]),
        parsed_items=[dict(item) for item in _json_list(row.get("parsed_items")) if isinstance(item, dict)],
        resume_payload=_json_object(row.get("resume_payload")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def review_item_from_row(row: dict[str, Any]) -> ReviewItemRecord:
    bbox = row.get("bbox")
    flags = row.get("quality_flags")
    return ReviewItemRecord(
        id=str(row["id"]),
        batch_id=str(row["batch_id"]),
        doc_id=str(row["doc_id"]),
        doc_title=str(row.get("doc_title") or row["doc_id"]),
        item_index=int(row.get("item_index") or 0),
        item_type=str(row.get("item_type") or "text"),
        page_start=row.get("page_start"),
        page_end=row.get("page_end"),
        bbox=[float(item) for item in bbox] if isinstance(bbox, list) else None,
        quality_flags=tuple(str(item) for item in flags) if isinstance(flags, list) else tuple(),
        partial_text=str(row.get("partial_text") or ""),
        corrected_text=str(row["corrected_text"]) if row.get("corrected_text") is not None else None,
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        status=str(row["status"]),
        assigned_to=str(row["assigned_to"]) if row.get("assigned_to") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def image_review_batch_from_row(row: dict[str, Any]) -> ImageReviewBatchRecord:
    return ImageReviewBatchRecord(
        id=str(row["id"]),
        job_id=str(row["job_id"]),
        doc_id=str(row["doc_id"]),
        doc_title=str(row.get("doc_title") or row["doc_id"]),
        status=str(row["status"]),
        parsed_items=[dict(item) for item in _json_list(row.get("parsed_items")) if isinstance(item, dict)],
        resume_payload=_json_object(row.get("resume_payload")),
        candidate_count=int(row.get("candidate_count") or 0),
        recommended_count=int(row.get("recommended_count") or 0),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def image_review_candidate_from_row(row: dict[str, Any]) -> ImageReviewCandidateRecord:
    bbox = row.get("bbox")
    flags = row.get("quality_flags")
    return ImageReviewCandidateRecord(
        id=str(row["id"]),
        batch_id=str(row["batch_id"]),
        doc_id=str(row["doc_id"]),
        doc_title=str(row.get("doc_title") or row["doc_id"]),
        candidate_key=str(row["candidate_key"]),
        filename=str(row.get("filename") or "image"),
        source_kind=str(row.get("source_kind") or "pdf_image"),
        page=row.get("page"),
        bbox=[float(item) for item in bbox] if isinstance(bbox, list) else None,
        page_area_ratio=float(row["page_area_ratio"]) if row.get("page_area_ratio") is not None else None,
        object_path=str(row["object_path"]),
        content_type=str(row.get("content_type") or "image/png"),
        width=int(row["width"]) if row.get("width") is not None else None,
        height=int(row["height"]) if row.get("height") is not None else None,
        content_hash=str(row["content_hash"]),
        quality_flags=tuple(str(item) for item in flags) if isinstance(flags, list) else tuple(),
        score=int(row.get("score") or 0),
        recommended=bool(row.get("recommended")),
        status=str(row["status"]),
        assigned_to=str(row["assigned_to"]) if row.get("assigned_to") else None,
        skip_reason=str(row["skip_reason"]) if row.get("skip_reason") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def image_asset_from_row(row: dict[str, Any]) -> DocumentImageAssetRecord:
    bbox = row.get("bbox")
    flags = row.get("quality_flags")
    return DocumentImageAssetRecord(
        id=str(row["id"]),
        doc_id=str(row["doc_id"]),
        job_id=str(row["job_id"]) if row.get("job_id") else None,
        source_kind=str(row.get("source_kind") or "image"),
        page=row.get("page"),
        bbox=[float(item) for item in bbox] if isinstance(bbox, list) else None,
        object_path=str(row["object_path"]),
        content_type=str(row.get("content_type") or "image/jpeg"),
        width=int(row["width"]) if row.get("width") is not None else None,
        height=int(row["height"]) if row.get("height") is not None else None,
        content_hash=str(row["content_hash"]),
        extracted_text=str(row["extracted_text"]) if row.get("extracted_text") is not None else None,
        caption=str(row["caption"]) if row.get("caption") is not None else None,
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        quality_flags=tuple(str(item) for item in flags) if isinstance(flags, list) else tuple(),
        created_at=row.get("created_at"),
    )


def _validate_edge(conn: Any, new_doc_id: str, old_doc_id: str) -> None:
    if old_doc_id == new_doc_id:
        raise ValueError("document cannot supersede itself")
    exists = conn.execute("SELECT 1 FROM documents WHERE id = %s AND deleted_at IS NULL", (old_doc_id,)).fetchone()
    if not exists:
        raise ValueError(f"superseded document does not exist: {old_doc_id}")
    cycle = conn.execute(
        """
        WITH RECURSIVE reach(id) AS (
            VALUES (%s::uuid)
            UNION SELECT new_doc_id FROM supersession_edges JOIN reach ON old_doc_id = reach.id
        )
        SELECT 1 FROM reach WHERE id = %s::uuid LIMIT 1
        """,
        (new_doc_id, old_doc_id),
    ).fetchone()
    if cycle:
        raise ValueError("supersession would create a cycle")


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            normalized.append(text)
    return normalized
