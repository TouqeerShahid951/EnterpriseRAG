"""PostgreSQL ingestion-job visibility search."""

from __future__ import annotations

from typing import Any

from ..job_models import IngestJobAccess, IngestJobFilters, IngestJobPage
from .job_postgres_rows import _job_view_from_row


class PostgresIngestJobSearchMixin:
    def search_visible_ingest_jobs(
        self,
        *,
        access: IngestJobAccess,
        filters: IngestJobFilters,
        limit: int | None,
        offset: int = 0,
    ) -> IngestJobPage:
        _validate_page(limit=limit, offset=offset)
        where_sql, params = _visible_job_where(access, filters)
        rows = self._execute_all(
            f"""
            WITH filtered AS (
                SELECT
                    job.id::text AS id,
                    job.doc_id::text AS doc_id,
                    job.retry_of_job_id::text AS retry_of_job_id,
                    COALESCE(job.origin, 'unknown') AS origin,
                    job.status,
                    job.progress_pct,
                    job.stage_progress,
                    job.attempt_count,
                    job.last_heartbeat_at,
                    job.run_token,
                    job.warnings,
                    job.parser_provenance,
                    job.error_code,
                    job.error_message_safe,
                    job.created_at,
                    job.updated_at,
                    job.completed_at,
                    COALESCE(document.title, document.id::text) AS document_title,
                    document.group_path,
                    document.clearance_level,
                    document.uploaded_by::text AS uploaded_by
                FROM ingest_jobs job
                JOIN documents document ON document.id = job.doc_id
                WHERE {where_sql}
            ),
            page AS (
                SELECT *
                FROM filtered
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
            ),
            counted AS (
                SELECT COUNT(*)::bigint AS total FROM filtered
            )
            SELECT page.*, counted.total
            FROM counted
            LEFT JOIN page ON TRUE
            ORDER BY page.created_at DESC NULLS LAST, page.id DESC NULLS LAST
            """,
            (*params, limit, offset),
        )
        total = int(rows[0]["total"]) if rows else 0
        items = tuple(
            _job_view_from_row(row) for row in rows if row.get("id") is not None
        )
        return IngestJobPage(items=items, total=total)


def _visible_job_where(
    access: IngestJobAccess,
    filters: IngestJobFilters,
) -> tuple[str, tuple[Any, ...]]:
    clauses = ["document.clearance_level = ANY(%s::text[])"]
    params: list[Any] = [list(access.clearance_levels)]
    if access.group_paths is not None:
        visible_groups = list(access.group_paths)
        clauses.append(
            """
            (
                document.group_path = ANY(%s::text[])
                OR EXISTS (
                    SELECT 1
                    FROM document_shares share
                    WHERE share.document_id = document.id
                      AND share.group_path = ANY(%s::text[])
                )
            )
            """
        )
        params.extend([visible_groups, visible_groups])
    if filters.status:
        clauses.append("job.status = %s")
        params.append(filters.status)
    if filters.origin:
        clauses.append("job.origin = %s")
        params.append(filters.origin)
    if filters.group_path:
        clauses.append("document.group_path = %s")
        params.append(filters.group_path)
    query = (filters.search or "").strip().lower()
    if query:
        pattern = f"%{query}%"
        clauses.append(
            """
            (
                lower(job.id::text) LIKE %s
                OR lower(job.doc_id::text) LIKE %s
                OR lower(COALESCE(document.title, '')) LIKE %s
                OR lower(document.group_path) LIKE %s
            )
            """
        )
        params.extend([pattern, pattern, pattern, pattern])
    if filters.created_from:
        clauses.append("job.created_at >= %s")
        params.append(filters.created_from)
    if filters.created_to:
        clauses.append("job.created_at <= %s")
        params.append(filters.created_to)
    if filters.uploaded_by_user_id:
        clauses.append("document.uploaded_by = %s")
        params.append(filters.uploaded_by_user_id)
    return " AND ".join(f"({clause})" for clause in clauses), tuple(params)



def _validate_page(*, limit: int | None, offset: int) -> None:
    if limit is not None and limit < 0:
        raise ValueError("ingestion job search limit must be nonnegative")
    if offset < 0:
        raise ValueError("ingestion job search offset must be nonnegative")
