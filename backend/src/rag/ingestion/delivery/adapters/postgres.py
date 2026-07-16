"""PostgreSQL adapter for atomic ingestion delivery."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import json
from typing import Any

from ...adapters.job_postgres_rows import _job_from_row, _require_row
from ..models import (
    IngestDeliveryMutation,
    IngestOutboxRecord,
    IngestWorkerDeliveryClaim,
    PendingIngestDelivery,
)


class PostgresIngestDeliveryRepositoryMixin:
    def create_queued_job_with_delivery(
        self,
        delivery: PendingIngestDelivery,
        *,
        doc_id: str,
        origin: str,
        retry_of_job_id: str | None,
    ) -> IngestDeliveryMutation:
        _validate_delivery(delivery, job_id=delivery.job_id, doc_id=doc_id)
        with self._connect() as conn:
            with conn.transaction():
                current_row = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s FOR UPDATE",
                    (delivery.job_id,),
                ).fetchone()
                if current_row is not None:
                    existing = _existing_delivery(conn, delivery)
                    if existing is not None:
                        return IngestDeliveryMutation(
                            _job_from_row(current_row), existing, False
                        )
                    raise ValueError("ingestion job already exists")
                row = conn.execute(
                    """
                    INSERT INTO ingest_jobs (
                        id, doc_id, retry_of_job_id, origin, status, progress_pct,
                        active_delivery_id
                    )
                    VALUES (%s, %s, %s, %s, 'queued', 0, %s)
                    RETURNING *
                    """,
                    (
                        delivery.job_id,
                        doc_id,
                        retry_of_job_id,
                        origin,
                        delivery.delivery_id,
                    ),
                ).fetchone()
                outbox = _insert_delivery(conn, delivery)
                _update_document_status(conn, doc_id, "queued")
        return IngestDeliveryMutation(
            _job_from_row(_require_row(row, "ingestion delivery job insert")),
            outbox,
            True,
        )

    def queue_existing_job_with_delivery(
        self,
        job_id: str,
        delivery: PendingIngestDelivery,
        *,
        expected_statuses: frozenset[str],
        increment_review_resume: bool,
    ) -> IngestDeliveryMutation:
        _validate_delivery(delivery, job_id=job_id)
        with self._connect() as conn:
            with conn.transaction():
                current_row = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if current_row is None:
                    return IngestDeliveryMutation(None, None, False)
                _validate_delivery(
                    delivery,
                    job_id=job_id,
                    doc_id=str(current_row["doc_id"]),
                )
                existing = _existing_delivery(conn, delivery)
                if existing is not None:
                    return IngestDeliveryMutation(
                        _job_from_row(current_row), existing, False
                    )
                if str(current_row["status"]) not in expected_statuses:
                    return IngestDeliveryMutation(
                        _job_from_row(current_row), None, False
                    )
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = 'queued',
                        progress_pct = 0,
                        stage_progress = NULL,
                        error_code = NULL,
                        error_message_safe = NULL,
                        run_token = NULL,
                        active_delivery_id = %s,
                        review_resume_count = review_resume_count + %s,
                        completed_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s AND status = %s
                    RETURNING *
                    """,
                    (
                        delivery.delivery_id,
                        int(increment_review_resume),
                        job_id,
                        current_row["status"],
                    ),
                ).fetchone()
                updated_row = _require_row(row, "locked ingestion delivery update")
                outbox = _insert_delivery(conn, delivery)
                _update_document_status(conn, str(updated_row["doc_id"]), "queued")
        return IngestDeliveryMutation(_job_from_row(updated_row), outbox, True)

    def recover_stale_job_with_delivery(
        self,
        job_id: str,
        delivery: PendingIngestDelivery,
        *,
        stale_before: datetime,
        max_failures: int,
    ) -> IngestDeliveryMutation:
        _validate_delivery(delivery, job_id=job_id)
        with self._connect() as conn:
            with conn.transaction():
                current_row = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if current_row is None:
                    return IngestDeliveryMutation(None, None, False)
                existing = _existing_delivery(conn, delivery)
                if existing is not None:
                    current = _job_from_row(current_row)
                    return IngestDeliveryMutation(
                        current,
                        existing,
                        False,
                        current.failure_attempt_count >= max_failures,
                    )
                current = _job_from_row(current_row)
                last_activity = (
                    current.last_heartbeat_at or current.updated_at or current.created_at
                )
                if (
                    current.status != "processing"
                    or current.failure_attempt_count >= max_failures
                    or (last_activity is not None and last_activity >= stale_before)
                ):
                    return IngestDeliveryMutation(
                        current,
                        None,
                        False,
                        current.failure_attempt_count >= max_failures,
                    )
                failure_count = current.failure_attempt_count + 1
                exhausted = failure_count >= max_failures
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = %s,
                        progress_pct = %s,
                        failure_attempt_count = %s,
                        last_failure_run_token = run_token,
                        run_token = NULL,
                        active_delivery_id = %s,
                        error_code = %s,
                        error_message_safe = %s,
                        completed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                        updated_at = NOW()
                    WHERE id = %s AND status = 'processing'
                    RETURNING *
                    """,
                    (
                        "failed" if exhausted else "queued",
                        100 if exhausted else 0,
                        failure_count,
                        None if exhausted else delivery.delivery_id,
                        "retry_exhausted" if exhausted else None,
                        (
                            "Ingestion could not complete after the retry limit."
                            if exhausted
                            else None
                        ),
                        exhausted,
                        job_id,
                    ),
                ).fetchone()
                updated_row = _require_row(row, "stale ingestion delivery recovery")
                outbox = None if exhausted else _insert_delivery(conn, delivery)
                _update_document_status(
                    conn,
                    str(updated_row["doc_id"]),
                    "failed" if exhausted else "queued",
                )
        return IngestDeliveryMutation(
            _job_from_row(updated_row), outbox, True, exhausted
        )

    def record_worker_failure_with_delivery(
        self,
        job_id: str,
        *,
        run_token: str,
        max_failures: int,
        error_code: str,
        error_message_safe: str,
        delivery: PendingIngestDelivery | None,
    ) -> IngestDeliveryMutation:
        if delivery is not None:
            _validate_delivery(delivery, job_id=job_id)
        with self._connect() as conn:
            with conn.transaction():
                current_row = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if current_row is None:
                    return IngestDeliveryMutation(None, None, False)
                current = _job_from_row(current_row)
                if current.last_failure_run_token == run_token:
                    existing = _delivery_for_id(
                        conn, current.active_delivery_id
                    )
                    return IngestDeliveryMutation(
                        current,
                        existing,
                        False,
                        current.failure_attempt_count >= max_failures,
                    )
                if current.status != "processing" or current.run_token != run_token:
                    return IngestDeliveryMutation(current, None, False)
                failure_count = current.failure_attempt_count + 1
                retrying = delivery is not None and failure_count < max_failures
                exhausted = failure_count >= max_failures
                row = conn.execute(
                    """
                    UPDATE ingest_jobs
                    SET status = %s,
                        progress_pct = %s,
                        failure_attempt_count = %s,
                        last_failure_run_token = %s,
                        run_token = NULL,
                        active_delivery_id = %s,
                        error_code = %s,
                        error_message_safe = %s,
                        completed_at = CASE WHEN %s THEN NULL ELSE NOW() END,
                        updated_at = NOW()
                    WHERE id = %s AND status = 'processing' AND run_token = %s
                    RETURNING *
                    """,
                    (
                        "queued" if retrying else "failed",
                        0 if retrying else 100,
                        failure_count,
                        run_token,
                        delivery.delivery_id if retrying and delivery else None,
                        None if retrying else error_code,
                        None if retrying else error_message_safe,
                        retrying,
                        job_id,
                        run_token,
                    ),
                ).fetchone()
                updated_row = _require_row(row, "ingestion worker failure update")
                outbox = (
                    _insert_delivery(conn, delivery)
                    if retrying and delivery is not None
                    else None
                )
                _update_document_status(
                    conn,
                    str(updated_row["doc_id"]),
                    "queued" if retrying else "failed",
                )
        return IngestDeliveryMutation(
            _job_from_row(updated_row), outbox, True, exhausted
        )

    def claim_worker_delivery(
        self,
        job_id: str,
        *,
        delivery_id: str,
        run_token: str,
        max_failures: int,
    ) -> IngestWorkerDeliveryClaim:
        with self._connect() as conn:
            with conn.transaction():
                current_row = conn.execute(
                    "SELECT * FROM ingest_jobs WHERE id = %s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if current_row is None:
                    return IngestWorkerDeliveryClaim(None, False, "missing")
                current = _job_from_row(current_row)
                if current.active_delivery_id != delivery_id:
                    return IngestWorkerDeliveryClaim(
                        current, False, "duplicate"
                    )
                if current.status == "processing" and current.run_token == run_token:
                    return IngestWorkerDeliveryClaim(current, True, "accepted")
                if current.failure_attempt_count >= max_failures:
                    return IngestWorkerDeliveryClaim(current, False, "exhausted")
                if current.status == "processing":
                    return IngestWorkerDeliveryClaim(current, False, "busy")
                if current.status != "queued":
                    return IngestWorkerDeliveryClaim(current, False, "duplicate")
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
                      AND status = 'queued'
                      AND active_delivery_id = %s
                      AND failure_attempt_count < %s
                    RETURNING *
                    """,
                    (run_token, job_id, delivery_id, max_failures),
                ).fetchone()
                updated_row = _require_row(row, "ingestion worker delivery claim")
                _update_document_status(
                    conn, str(updated_row["doc_id"]), "processing"
                )
        return IngestWorkerDeliveryClaim(
            _job_from_row(updated_row), True, "accepted"
        )

    def claim_due_outbox(
        self,
        *,
        claim_token: str,
        limit: int,
        lease_seconds: int,
        now: datetime,
    ) -> tuple[IngestOutboxRecord, ...]:
        claim_expires_at = now + timedelta(seconds=lease_seconds)
        with self._connect() as conn:
            with conn.transaction():
                rows = list(
                    conn.execute(
                        """
                        WITH due AS (
                            SELECT delivery_id
                            FROM ingest_outbox
                            WHERE published_at IS NULL
                              AND available_at <= %s
                              AND (
                                  claim_expires_at IS NULL
                                  OR claim_expires_at <= %s
                              )
                            ORDER BY available_at, created_at, delivery_id
                            LIMIT %s
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE ingest_outbox AS outbox
                        SET claim_token = %s,
                            claim_expires_at = %s,
                            publish_attempt_count = publish_attempt_count + 1,
                            updated_at = %s
                        FROM due
                        WHERE outbox.delivery_id = due.delivery_id
                        RETURNING outbox.*
                        """,
                        (
                            now,
                            now,
                            limit,
                            claim_token,
                            claim_expires_at,
                            now,
                        ),
                    ).fetchall()
                )
                delivery_counts = Counter(str(row["job_id"]) for row in rows)
                for job_id in sorted(delivery_counts):
                    conn.execute(
                        """
                        UPDATE ingest_jobs
                        SET delivery_count = delivery_count + %s,
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (delivery_counts[job_id], now, job_id),
                    )
        deliveries = [_outbox_from_row(row) for row in rows]
        deliveries.sort(
            key=lambda item: (
                item.available_at,
                item.created_at or item.available_at,
                item.delivery_id,
            )
        )
        return tuple(deliveries)

    def ack_outbox_delivery(self, delivery_id: str, *, claim_token: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE ingest_outbox
                SET published_at = NOW(),
                    claim_token = NULL,
                    claim_expires_at = NULL,
                    last_error_code = NULL,
                    updated_at = NOW()
                WHERE delivery_id = %s
                  AND published_at IS NULL
                  AND claim_token = %s
                RETURNING delivery_id
                """,
                (delivery_id, claim_token),
            ).fetchone()
        return row is not None

    def release_outbox_delivery(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        available_at: datetime,
        error_code: str,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE ingest_outbox
                SET available_at = %s,
                    claim_token = NULL,
                    claim_expires_at = NULL,
                    last_error_code = %s,
                    updated_at = NOW()
                WHERE delivery_id = %s
                  AND published_at IS NULL
                  AND claim_token = %s
                RETURNING delivery_id
                """,
                (available_at, error_code, delivery_id, claim_token),
            ).fetchone()
        return row is not None


def _validate_delivery(
    delivery: PendingIngestDelivery,
    *,
    job_id: str,
    doc_id: str | None = None,
) -> None:
    if delivery.job_id != job_id or delivery.payload.get("job_id") != job_id:
        raise ValueError("delivery job_id does not match ingestion job")
    if delivery.payload.get("delivery_id") != delivery.delivery_id:
        raise ValueError("delivery payload does not contain its delivery_id")
    if doc_id is not None and delivery.payload.get("doc_id") != doc_id:
        raise ValueError("delivery doc_id does not match ingestion job")


def _existing_delivery(conn: Any, delivery: PendingIngestDelivery) -> IngestOutboxRecord | None:
    row = conn.execute(
        "SELECT * FROM ingest_outbox WHERE delivery_id = %s FOR UPDATE",
        (delivery.delivery_id,),
    ).fetchone()
    if row is None:
        return None
    existing = _outbox_from_row(row)
    if (
        existing.job_id != delivery.job_id
        or existing.event_kind != delivery.event_kind
        or existing.payload != delivery.payload
    ):
        raise ValueError("delivery_id is already used by a different delivery")
    return existing


def _delivery_for_id(conn: Any, delivery_id: str | None) -> IngestOutboxRecord | None:
    if delivery_id is None:
        return None
    row = conn.execute(
        "SELECT * FROM ingest_outbox WHERE delivery_id = %s",
        (delivery_id,),
    ).fetchone()
    return _outbox_from_row(row) if row is not None else None


def _insert_delivery(conn: Any, delivery: PendingIngestDelivery) -> IngestOutboxRecord:
    row = conn.execute(
        """
        INSERT INTO ingest_outbox (
            delivery_id, job_id, event_kind, payload, available_at
        )
        VALUES (%s, %s, %s, %s::jsonb, %s)
        RETURNING *
        """,
        (
            delivery.delivery_id,
            delivery.job_id,
            delivery.event_kind,
            json.dumps(delivery.payload),
            delivery.available_at,
        ),
    ).fetchone()
    return _outbox_from_row(_require_row(row, "ingestion outbox insert"))


def _update_document_status(conn: Any, doc_id: str, status: str) -> None:
    conn.execute(
        "UPDATE documents SET ingest_status = %s, updated_at = NOW() WHERE id = %s",
        (status, doc_id),
    )


def _outbox_from_row(row: dict[str, Any]) -> IngestOutboxRecord:
    payload = row.get("payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise RuntimeError("ingest outbox payload is not an object")
    return IngestOutboxRecord(
        delivery_id=str(row["delivery_id"]),
        job_id=str(row["job_id"]),
        event_kind=str(row["event_kind"]),
        payload=dict(payload),
        available_at=row["available_at"],
        claim_token=str(row["claim_token"]) if row.get("claim_token") else None,
        claim_expires_at=row.get("claim_expires_at"),
        publish_attempt_count=int(row.get("publish_attempt_count") or 0),
        published_at=row.get("published_at"),
        last_error_code=(
            str(row["last_error_code"]) if row.get("last_error_code") else None
        ),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
