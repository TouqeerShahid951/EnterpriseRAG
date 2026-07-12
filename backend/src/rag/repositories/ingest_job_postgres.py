"""PostgreSQL ingestion-job repository."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .ingest_job_models import (
    IngestAttemptResult,
    IngestJobCancellationResult,
    IngestJobMutationResult,
    IngestJobRecord,
)
from .postgres import PostgresConnectionMixin


class PostgresIngestJobRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

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
                conn.execute(
                    "UPDATE documents SET ingest_status = %s, updated_at = NOW() WHERE id = %s",
                    (status, doc_id),
                )
        return job_from_row(row)

    def get_ingest_job(self, job_id: str) -> IngestJobRecord | None:
        row = self._execute_optional(
            "SELECT * FROM ingest_jobs WHERE id = %s", (job_id,)
        )
        return job_from_row(row) if row else None

    def list_ingest_jobs(self) -> list[IngestJobRecord]:
        rows = self._execute_all(
            "SELECT * FROM ingest_jobs ORDER BY created_at DESC, id DESC"
        )
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
                if (
                    expected_statuses is not None
                    and current.status not in expected_statuses
                ):
                    return IngestJobMutationResult(job=current, changed=False)
                last_activity = (
                    current.last_heartbeat_at
                    or current.updated_at
                    or current.created_at
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
                            json.dumps(
                                {"doc_id": str(row["doc_id"]), "provenance": provenance}
                            ),
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


def job_from_row(row: dict[str, Any]) -> IngestJobRecord:
    return IngestJobRecord(
        id=str(row["id"]),
        doc_id=str(row["doc_id"]),
        retry_of_job_id=str(row["retry_of_job_id"])
        if row.get("retry_of_job_id")
        else None,
        origin=str(row.get("origin") or "unknown"),
        status=row["status"],
        progress_pct=int(row["progress_pct"]),
        stage_progress=_json_object(row.get("stage_progress"))
        if row.get("stage_progress") is not None
        else None,
        attempt_count=int(row.get("attempt_count") or 0),
        last_heartbeat_at=row.get("last_heartbeat_at"),
        run_token=str(row["run_token"]) if row.get("run_token") else None,
        warnings=tuple(str(value) for value in _json_list(row.get("warnings"))),
        parser_provenance=_json_object(row.get("parser_provenance"))
        if row.get("parser_provenance") is not None
        else None,
        error_code=row.get("error_code"),
        error_message_safe=row.get("error_message_safe"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        completed_at=row.get("completed_at"),
    )


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
