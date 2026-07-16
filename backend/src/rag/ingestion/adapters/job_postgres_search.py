"""PostgreSQL ingestion-job visibility search."""

from __future__ import annotations

from typing import Any

from ..job_models import (
    IngestJobAccess,
    IngestJobFilters,
    IngestJobPage,
    IngestJobSummary,
)
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
                    job.delivery_count,
                    job.failure_attempt_count,
                    job.review_resume_count,
                    job.resource_promotion_count,
                    job.active_delivery_id,
                    job.last_failure_run_token,
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

    def summarize_visible_ingest_jobs(
        self,
        *,
        access: IngestJobAccess,
        filters: IngestJobFilters,
    ) -> IngestJobSummary:
        where_sql, params = _visible_job_where(access, filters)
        rows = self._execute_all(
            f"""
            WITH filtered AS (
                SELECT
                    job.id::text AS id,
                    job.doc_id::text AS doc_id,
                    CASE
                        WHEN COALESCE(job.origin, 'unknown') IN (
                            'upload', 'reingest', 'restore', 'folder', 'connector', 'unknown'
                        )
                        THEN COALESCE(job.origin, 'unknown')
                        ELSE 'unknown'
                    END AS origin,
                    job.status,
                    job.progress_pct,
                    job.stage_progress,
                    job.created_at,
                    job.updated_at
                FROM ingest_jobs job
                JOIN documents document ON document.id = job.doc_id
                WHERE {where_sql}
            ),
            staged AS (
                SELECT filtered.*, {_ingest_stage_sql()} AS stage
                FROM filtered
            ),
            latest AS (
                SELECT
                    status,
                    ROW_NUMBER() OVER (
                        PARTITION BY doc_id
                        ORDER BY GREATEST(created_at, updated_at) DESC NULLS LAST, id DESC
                    ) AS document_rank
                FROM filtered
            )
            SELECT 'metric' AS dimension, 'total' AS name, COUNT(*)::bigint AS value
            FROM filtered
            UNION ALL
            SELECT
                'metric',
                'active',
                COUNT(*) FILTER (
                    WHERE status IN ('scheduled', 'queued', 'processing', 'human_review')
                )::bigint
            FROM filtered
            UNION ALL
            SELECT
                'metric',
                'needs_attention',
                COUNT(*) FILTER (
                    WHERE document_rank = 1
                      AND status IN (
                          'scheduled', 'queued', 'processing', 'human_review', 'failed'
                      )
                )::bigint
            FROM latest
            UNION ALL
            SELECT 'status', status, COUNT(*)::bigint
            FROM staged
            GROUP BY status
            UNION ALL
            SELECT 'stage', stage, COUNT(*)::bigint
            FROM staged
            GROUP BY stage
            UNION ALL
            SELECT 'origin', origin, COUNT(*)::bigint
            FROM staged
            GROUP BY origin
            """,
            params,
        )
        metrics: dict[str, int] = {}
        counts: dict[str, dict[str, int]] = {
            "status": {},
            "stage": {},
            "origin": {},
        }
        for row in rows:
            dimension = str(row["dimension"])
            name = str(row["name"])
            value = int(row["value"])
            if dimension == "metric":
                metrics[name] = value
            elif dimension in counts:
                counts[dimension][name] = value
        return IngestJobSummary(
            total=metrics.get("total", 0),
            active=metrics.get("active", 0),
            needs_attention=metrics.get("needs_attention", 0),
            status_counts=counts["status"],
            stage_counts=counts["stage"],
            origin_counts=counts["origin"],
        )


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


def _ingest_stage_sql() -> str:
    label = "lower(btrim(COALESCE(stage_progress->>'label', '')))"
    unit = "lower(COALESCE(stage_progress->>'unit', ''))"
    return f"""
        CASE
            WHEN status IN ('complete', 'failed', 'human_review', 'cancelled') THEN status
            WHEN status = 'queued' THEN 'queued'
            WHEN status = 'scheduled' THEN 'scheduled'
            WHEN {label} LIKE 'docling%%' THEN 'docling_repair'
            WHEN {label} LIKE 'vision layout%%' THEN 'vision_layout_repair'
            WHEN {unit} = 'images' OR {label} LIKE 'image analysis%%' THEN 'image_analysis'
            WHEN {unit} = 'metadata'
              OR {label} LIKE '%%metadata model%%'
              OR {label} LIKE 'requesting metadata%%'
              OR {label} LIKE 'waiting on%%' THEN 'metadata_enrichment'
            WHEN {label} LIKE 'embedding chunk%%'
              OR {label} LIKE 'generating sparse vectors%%' THEN 'embedding_chunks'
            WHEN {label} LIKE '%%qdrant%%'
              OR {label} LIKE 'prepared vectors%%'
              OR {label} LIKE 'indexed vectors%%' THEN 'indexing_vectors'
            WHEN {label} LIKE 'built retrieval chunks%%' THEN 'chunking_document'
            WHEN {label} LIKE 'parsed %%'
              OR {label} LIKE 'parsing page%%' THEN 'parsing_document'
            WHEN progress_pct < 5 THEN 'queued'
            WHEN progress_pct < 20 THEN 'reading_file'
            WHEN progress_pct < 35 THEN 'parsing_document'
            WHEN progress_pct < 36 THEN 'image_analysis'
            WHEN progress_pct < 50 THEN 'metadata_enrichment'
            WHEN progress_pct < 60 THEN 'chunking_document'
            WHEN progress_pct < 65 THEN 'saving_claims'
            WHEN progress_pct < 78 THEN 'embedding_chunks'
            WHEN progress_pct < 92 THEN 'indexing_vectors'
            ELSE 'finalizing'
        END
    """



def _validate_page(*, limit: int | None, offset: int) -> None:
    if limit is not None and limit < 0:
        raise ValueError("ingestion job search limit must be nonnegative")
    if offset < 0:
        raise ValueError("ingestion job search offset must be nonnegative")
