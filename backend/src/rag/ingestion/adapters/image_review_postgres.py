"""PostgreSQL persistence for image-review workflows."""

from __future__ import annotations

import json
from typing import Any

from ...repositories.postgres import PostgresConnectionMixin
from ..review_models import (
    ImageReviewBatchClosedError,
    ImageReviewBatchRecord,
    ImageReviewCandidateRecord,
    ImageReviewDecisionRecord,
)


class PostgresImageReviewRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

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
                        sum(
                            1
                            for candidate in candidates
                            if bool(candidate.get("recommended", True))
                        ),
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
                            (
                                json.dumps(candidate["bbox"])
                                if candidate.get("bbox") is not None
                                else None
                            ),
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

    def list_image_review_batches(
        self, *, status: str = "pending"
    ) -> list[ImageReviewBatchRecord]:
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
        params: tuple[Any, ...] = (
            (batch_id, status) if status is not None else (batch_id,)
        )
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

    def get_image_review_candidate(
        self, candidate_id: str
    ) -> ImageReviewCandidateRecord | None:
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
                batch_status = _lock_image_review_batch(conn, batch_id)
                if batch_status is None:
                    return None
                if batch_status == "rejected":
                    raise ImageReviewBatchClosedError(batch_id, batch_status)
                changed_ids = _apply_candidate_decisions(
                    conn,
                    batch_id=batch_id,
                    approve_candidate_ids=approve_candidate_ids,
                    skip_candidate_ids=skip_candidate_ids,
                    reviewer_id=reviewer_id,
                    approve_recommended=approve_recommended,
                    skip_remaining=skip_remaining,
                )
                complete = _update_image_review_batch_status(conn, batch_id)
                batch_row, candidate_rows = _load_image_review_decision_rows(
                    conn, batch_id, changed_ids
                )
        return ImageReviewDecisionRecord(
            batch=image_review_batch_from_row(batch_row),
            candidates=tuple(
                image_review_candidate_from_row(row) for row in candidate_rows
            ),
            batch_complete=bool(complete),
        )


def _lock_image_review_batch(conn: Any, batch_id: str) -> str | None:
    row = conn.execute(
        "SELECT status FROM image_review_batches WHERE id = %s FOR UPDATE",
        (batch_id,),
    ).fetchone()
    return str(row["status"]) if row is not None else None


def _apply_candidate_decisions(
    conn: Any,
    *,
    batch_id: str,
    approve_candidate_ids: list[str],
    skip_candidate_ids: list[str],
    reviewer_id: str,
    approve_recommended: bool,
    skip_remaining: bool,
) -> set[str]:
    changed_ids: set[str] = set()
    if approve_candidate_ids:
        changed_ids.update(
            _approve_selected_candidates(
                conn, batch_id, approve_candidate_ids, reviewer_id
            )
        )
    if approve_recommended:
        changed_ids.update(_approve_recommended_candidates(conn, batch_id, reviewer_id))
    if skip_candidate_ids:
        changed_ids.update(
            _skip_selected_candidates(conn, batch_id, skip_candidate_ids, reviewer_id)
        )
    if skip_remaining:
        changed_ids.update(_skip_remaining_candidates(conn, batch_id, reviewer_id))
    return changed_ids


def _approve_selected_candidates(
    conn: Any,
    batch_id: str,
    candidate_ids: list[str],
    reviewer_id: str,
) -> list[str]:
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
        (reviewer_id, batch_id, candidate_ids),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def _approve_recommended_candidates(
    conn: Any, batch_id: str, reviewer_id: str
) -> list[str]:
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
    return [str(row["id"]) for row in rows]


def _skip_selected_candidates(
    conn: Any,
    batch_id: str,
    candidate_ids: list[str],
    reviewer_id: str,
) -> list[str]:
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
        (reviewer_id, batch_id, candidate_ids),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def _skip_remaining_candidates(conn: Any, batch_id: str, reviewer_id: str) -> list[str]:
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
    return [str(row["id"]) for row in rows]


def _update_image_review_batch_status(conn: Any, batch_id: str) -> bool:
    complete = bool(
        conn.execute(
            """
        SELECT NOT EXISTS (
            SELECT 1 FROM image_review_candidates
            WHERE batch_id = %s AND status = 'pending'
        ) AS complete
        """,
            (batch_id,),
        ).fetchone()["complete"]
    )
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
        conn.execute(
            "UPDATE image_review_batches SET updated_at = NOW() WHERE id = %s",
            (batch_id,),
        )
    return complete


def _load_image_review_decision_rows(
    conn: Any,
    batch_id: str,
    changed_ids: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
    return batch_row, candidate_rows


def image_review_batch_from_row(row: dict[str, Any]) -> ImageReviewBatchRecord:
    return ImageReviewBatchRecord(
        id=str(row["id"]),
        job_id=str(row["job_id"]),
        doc_id=str(row["doc_id"]),
        doc_title=str(row.get("doc_title") or row["doc_id"]),
        status=str(row["status"]),
        parsed_items=[
            dict(item)
            for item in _json_list(row.get("parsed_items"))
            if isinstance(item, dict)
        ],
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
        page_area_ratio=float(row["page_area_ratio"])
        if row.get("page_area_ratio") is not None
        else None,
        object_path=str(row["object_path"]),
        content_type=str(row.get("content_type") or "image/png"),
        width=int(row["width"]) if row.get("width") is not None else None,
        height=int(row["height"]) if row.get("height") is not None else None,
        content_hash=str(row["content_hash"]),
        quality_flags=tuple(str(item) for item in flags)
        if isinstance(flags, list)
        else tuple(),
        score=int(row.get("score") or 0),
        recommended=bool(row.get("recommended")),
        status=str(row["status"]),
        assigned_to=str(row["assigned_to"]) if row.get("assigned_to") else None,
        skip_reason=str(row["skip_reason"]) if row.get("skip_reason") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
