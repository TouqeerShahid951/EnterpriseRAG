"""PostgreSQL audit query adapter."""

from __future__ import annotations

import json
from typing import Any

from ...shared.persistence import PostgresConnectionMixin
from ...shared.contracts.clearance import clearance_levels_at_or_below
from ..models import (
    AuditEventPage,
    AuditEventRecord,
    AuditFilters,
    AuditSummaryRecord,
    AuditViewerScope,
    EnrichedAuditEvent,
    MAX_AUDIT_SCAN_LIMIT,
    payload_document_title,
)


class PostgresAuditRepository(PostgresConnectionMixin):
    def __init__(self, *, database_url: str) -> None:
        self.database_url = database_url

    def search_visible_events_page(
        self,
        *,
        filters: AuditFilters,
        viewer: AuditViewerScope,
        limit: int,
        offset: int = 0,
    ) -> AuditEventPage:
        if limit < 1:
            raise ValueError("audit page limit must be positive")
        if offset < 0:
            raise ValueError("audit page offset must be nonnegative")
        clauses: list[str] = []
        params: list[object] = []
        if not viewer.global_access:
            visible_groups = sorted(viewer.group_paths)
            if not visible_groups:
                return AuditEventPage()
            allowed_clearances = list(
                clearance_levels_at_or_below(viewer.clearance_level)
            )
            clauses.append(
                """
                (
                    (
                        doc_id IS NULL
                        AND payload->>'group_path' = ANY(%s::text[])
                    )
                    OR (
                        doc_id IS NOT NULL
                        AND doc_deleted_at IS NULL
                        AND doc_clearance_level = ANY(%s::text[])
                        AND (
                            doc_group_path = ANY(%s::text[])
                            OR EXISTS (
                                SELECT 1
                                FROM document_shares share
                                WHERE share.document_id::text = doc_id
                                  AND share.group_path = ANY(%s::text[])
                            )
                        )
                    )
                )
                """
            )
            params.extend(
                [visible_groups, allowed_clearances, visible_groups, visible_groups]
            )
        _append_filter_clauses(clauses, params, filters)
        where_sql = (
            " AND ".join(f"({clause})" for clause in clauses) if clauses else "TRUE"
        )
        rows = self._execute_all(
            _audit_page_query(where_sql),
            (*params, limit, offset),
        )
        if not rows:
            return AuditEventPage()
        return AuditEventPage(
            items=tuple(
                _enriched_event_from_row(row)
                for row in rows
                if row.get("id") is not None
            ),
            total=int(rows[0]["summary_total"]),
            summary=_audit_summary_from_row(rows[0]),
        )

    def search_visible_events(
        self,
        *,
        filters: AuditFilters,
        viewer: AuditViewerScope,
        scan_limit: int,
    ) -> list[EnrichedAuditEvent]:
        page = self.search_visible_events_page(
            filters=filters,
            viewer=viewer,
            limit=max(1, min(scan_limit, MAX_AUDIT_SCAN_LIMIT)),
        )
        return list(page.items)


def audit_event_from_row(row: dict[str, Any]) -> AuditEventRecord:
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    return AuditEventRecord(
        id=str(row["id"]),
        event_type=str(row["event_type"]),
        actor_id=str(row["actor_id"])
        if row.get("actor_id") is not None
        else None,
        target_type=str(row["target_type"])
        if row.get("target_type") is not None
        else None,
        target_id=str(row["target_id"])
        if row.get("target_id") is not None
        else None,
        payload=dict(payload),
        created_at=row.get("created_at"),
    )


def _append_filter_clauses(
    clauses: list[str], params: list[object], filters: AuditFilters
) -> None:
    if filters.category:
        clauses.append("category = %s")
        params.append(filters.category)
    if filters.event_type:
        clauses.append("event_type = %s")
        params.append(filters.event_type)
    if filters.actor_query:
        clauses.append(
            "(strpos(lower(COALESCE(actor_id, '')), %s) > 0 "
            "OR strpos(lower(COALESCE(actor_email, '')), %s) > 0)"
        )
        params.extend([filters.actor_query, filters.actor_query])
    if filters.target_type:
        clauses.append("target_type = %s")
        params.append(filters.target_type)
    if filters.target_id:
        clauses.append("strpos(lower(COALESCE(target_id, '')), %s) > 0")
        params.append(filters.target_id)
    if filters.group_path:
        group = "/" + filters.group_path.strip().strip("/")
        clauses.append(
            """
            (
                payload->>'group_path' = %s
                OR strpos(payload->>'group_path', %s) = 1
                OR doc_group_path = %s
                OR strpos(doc_group_path, %s) = 1
            )
            """
        )
        params.extend([group, f"{group}/", group, f"{group}/"])
    if filters.created_from:
        clauses.append("created_at >= %s")
        params.append(filters.created_from)
    if filters.created_to:
        clauses.append("created_at <= %s")
        params.append(filters.created_to)
    if filters.search:
        query = filters.search.lower()
        clauses.append(
            """
            (
                strpos(lower(id), %s) > 0
                OR strpos(lower(event_type), %s) > 0
                OR strpos(lower(COALESCE(actor_id, '')), %s) > 0
                OR strpos(lower(COALESCE(actor_email, '')), %s) > 0
                OR strpos(lower(COALESCE(target_type, '')), %s) > 0
                OR strpos(lower(COALESCE(target_id, '')), %s) > 0
                OR strpos(lower(COALESCE(target_user_email, '')), %s) > 0
                OR strpos(lower(COALESCE(target_user_name, '')), %s) > 0
                OR strpos(lower(category), %s) > 0
                OR strpos(lower(COALESCE(payload::text, '')), %s) > 0
                OR strpos(lower(COALESCE(doc_title, '')), %s) > 0
                OR strpos(lower(COALESCE(doc_group_path, '')), %s) > 0
                OR strpos(lower(COALESCE(doc_clearance_level, '')), %s) > 0
            )
            """
        )
        params.extend([query] * 13)


def _audit_page_query(where_sql: str) -> str:
    return f"""
        WITH enriched AS (
            SELECT
                audit.id::text AS id,
                audit.event_type,
                audit.actor_id::text AS actor_id,
                audit.target_type,
                audit.target_id,
                audit.payload,
                audit.created_at,
                COALESCE(
                    actor.email,
                    CASE
                        WHEN audit.actor_id::text = audit.target_id THEN audit.payload->>'email'
                    END
                ) AS actor_email,
                CASE
                    WHEN audit.target_type = 'user' THEN COALESCE(target_user.email, audit.payload->>'email')
                END AS target_user_email,
                CASE
                    WHEN audit.target_type = 'user' THEN COALESCE(target_user.name, audit.payload->>'name')
                END AS target_user_name,
                CASE
                    WHEN audit.event_type LIKE 'auth.%%' THEN 'authentication'
                    WHEN audit.target_type = 'document'
                      OR audit.event_type LIKE 'upload.%%'
                      OR audit.event_type LIKE 'documents.%%'
                      OR audit.event_type LIKE 'folder_ingest.%%'
                      OR audit.event_type LIKE 'internal.document%%'
                      OR audit.event_type LIKE 'internal.supersession%%' THEN 'document'
                    WHEN audit.event_type LIKE 'ingest.%%'
                      OR audit.event_type LIKE 'internal.ingest.%%'
                      OR audit.event_type LIKE 'admin.ingest.%%' THEN 'ingestion'
                    WHEN audit.target_type = 'user'
                      OR audit.event_type LIKE 'admin.user.%%' THEN 'user'
                    WHEN audit.event_type LIKE 'review.%%' THEN 'review'
                    WHEN audit.event_type LIKE 'query.%%' THEN 'query'
                    ELSE 'system'
                END AS category,
                CASE
                    WHEN audit.target_type = 'document' THEN audit.target_id
                    ELSE audit.payload->>'doc_id'
                END AS doc_id,
                document.title AS doc_title,
                document.group_path AS doc_group_path,
                document.clearance_level AS doc_clearance_level,
                document.deleted_at AS doc_deleted_at
            FROM audit_log audit
            LEFT JOIN users actor ON actor.id = audit.actor_id
            LEFT JOIN users target_user ON audit.target_type = 'user' AND target_user.id::text = audit.target_id
            LEFT JOIN documents document
              ON document.id::text = CASE
                    WHEN audit.target_type = 'document' THEN audit.target_id
                    ELSE audit.payload->>'doc_id'
                 END
        ),
        filtered AS (
            SELECT *
            FROM enriched
            WHERE {where_sql}
        ),
        page AS (
            SELECT *
            FROM filtered
            ORDER BY created_at DESC, id DESC
            LIMIT %s OFFSET %s
        ),
        summary AS (
            SELECT
                COUNT(*)::bigint AS summary_total,
                COUNT(*) FILTER (
                    WHERE target_type = 'document'
                       OR doc_id IS NOT NULL
                       OR category = 'document'
                )::bigint AS summary_document_events,
                COUNT(*) FILTER (
                    WHERE category = 'authentication'
                )::bigint AS summary_auth_events,
                COUNT(*) FILTER (
                    WHERE actor_id IS NULL
                )::bigint AS summary_system_events,
                COUNT(DISTINCT actor_id) FILTER (
                    WHERE actor_id IS NOT NULL
                )::bigint AS summary_actor_count,
                COUNT(DISTINCT event_type)::bigint AS summary_event_type_count,
                COALESCE(
                    (
                        SELECT jsonb_object_agg(category, event_count)
                        FROM (
                            SELECT category, COUNT(*)::bigint AS event_count
                            FROM filtered
                            GROUP BY category
                        ) category_summary
                    ),
                    '{{}}'::jsonb
                ) AS summary_category_counts,
                COALESCE(
                    (
                        SELECT jsonb_object_agg(target_type_key, event_count)
                        FROM (
                            SELECT
                                COALESCE(target_type, 'workspace') AS target_type_key,
                                COUNT(*)::bigint AS event_count
                            FROM filtered
                            GROUP BY COALESCE(target_type, 'workspace')
                        ) target_summary
                    ),
                    '{{}}'::jsonb
                ) AS summary_target_type_counts,
                COALESCE(
                    (
                        SELECT jsonb_object_agg(event_type, event_count)
                        FROM (
                            SELECT event_type, COUNT(*)::bigint AS event_count
                            FROM filtered
                            GROUP BY event_type
                        ) event_summary
                    ),
                    '{{}}'::jsonb
                ) AS summary_event_type_counts
            FROM filtered
        )
        SELECT page.*, summary.*
        FROM summary
        LEFT JOIN page ON TRUE
        ORDER BY page.created_at DESC NULLS LAST, page.id DESC NULLS LAST
    """


def _audit_summary_from_row(row: dict[str, Any]) -> AuditSummaryRecord:
    return AuditSummaryRecord(
        total=int(row["summary_total"]),
        document_events=int(row["summary_document_events"]),
        auth_events=int(row["summary_auth_events"]),
        system_events=int(row["summary_system_events"]),
        actor_count=int(row["summary_actor_count"]),
        event_type_count=int(row["summary_event_type_count"]),
        category_counts=_count_map(row.get("summary_category_counts")),
        target_type_counts=_count_map(row.get("summary_target_type_counts")),
        event_type_counts=_count_map(row.get("summary_event_type_counts")),
    )


def _count_map(value: Any) -> dict[str, int]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        return {}
    return {str(key): int(count) for key, count in value.items()}


def _enriched_event_from_row(row: dict[str, Any]) -> EnrichedAuditEvent:
    record = audit_event_from_row(row)
    document_title = row.get("doc_title")
    if isinstance(document_title, str):
        document_title = document_title.strip() or None
    else:
        document_title = None
    return EnrichedAuditEvent(
        record=record,
        category=str(row["category"]),
        actor_email=str(row["actor_email"]) if row.get("actor_email") else None,
        target_user_email=str(row["target_user_email"])
        if row.get("target_user_email")
        else None,
        target_user_name=str(row["target_user_name"])
        if row.get("target_user_name")
        else None,
        target_document_title=document_title or payload_document_title(record.payload),
    )
