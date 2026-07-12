"""PostgreSQL persistence for text-based human review workflows."""

from __future__ import annotations

import json
from typing import Any

from ...repositories.postgres import PostgresConnectionMixin
from ..review_models import ReviewBatchRecord, ReviewDecisionRecord, ReviewItemRecord


class PostgresHumanReviewRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

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
                    (
                        job_id,
                        doc_id,
                        json.dumps(parsed_items),
                        json.dumps(resume_payload),
                    ),
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
        row = self._execute_optional(
            "SELECT * FROM human_review_batches WHERE id = %s", (batch_id,)
        )
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

    def approve_review_item(
        self,
        item_id: str,
        *,
        corrected_text: str,
        reviewer_id: str,
    ) -> ReviewDecisionRecord | None:
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
                    item_row = conn.execute(
                        "SELECT * FROM human_review_queue WHERE id = %s", (item_id,)
                    ).fetchone()
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
                    batch_row = conn.execute(
                        "SELECT * FROM human_review_batches WHERE id = %s",
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
        return ReviewDecisionRecord(
            item=review_item_from_row(item_detail),
            batch=review_batch_from_row(batch_row),
            batch_complete=bool(complete),
        )

    def reject_review_item(
        self, item_id: str, *, reviewer_id: str
    ) -> ReviewDecisionRecord | None:
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
                    item_row = conn.execute(
                        "SELECT * FROM human_review_queue WHERE id = %s", (item_id,)
                    ).fetchone()
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
        return ReviewDecisionRecord(
            item=review_item_from_row(item_detail),
            batch=review_batch_from_row(batch_row),
            batch_complete=False,
        )


def review_batch_from_row(row: dict[str, Any]) -> ReviewBatchRecord:
    return ReviewBatchRecord(
        id=str(row["id"]),
        job_id=str(row["job_id"]),
        doc_id=str(row["doc_id"]),
        status=str(row["status"]),
        parsed_items=[
            dict(item)
            for item in _json_list(row.get("parsed_items"))
            if isinstance(item, dict)
        ],
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
        quality_flags=tuple(str(item) for item in flags)
        if isinstance(flags, list)
        else tuple(),
        partial_text=str(row.get("partial_text") or ""),
        corrected_text=str(row["corrected_text"])
        if row.get("corrected_text") is not None
        else None,
        confidence=float(row["confidence"])
        if row.get("confidence") is not None
        else None,
        status=str(row["status"]),
        assigned_to=str(row["assigned_to"]) if row.get("assigned_to") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
