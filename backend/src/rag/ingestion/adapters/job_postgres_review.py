"""PostgreSQL ingestion-job review cleanup helpers."""

from __future__ import annotations

from typing import Any


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
    conn.execute(
        """
        UPDATE image_review_batches
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
    return len(item_rows) + len(image_rows)
