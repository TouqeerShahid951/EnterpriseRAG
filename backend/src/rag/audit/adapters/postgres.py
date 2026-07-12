"""PostgreSQL audit query adapter."""

from __future__ import annotations

import json
from typing import Any

from ...shared.persistence import PostgresConnectionMixin
from ...shared.contracts.clearance import clearance_levels_at_or_below
from ..models import (
    AuditEventRecord,
    AuditFilters,
    AuditViewerScope,
    EnrichedAuditEvent,
    MAX_AUDIT_SCAN_LIMIT,
    payload_document_title,
)


class PostgresAuditRepository(PostgresConnectionMixin):
    def __init__(self, *, database_url: str) -> None:
        self.database_url = database_url

    def search_visible_events(
        self,
        *,
        filters: AuditFilters,
        viewer: AuditViewerScope,
        scan_limit: int,
    ) -> list[EnrichedAuditEvent]:
        clauses: list[str] = []
        params: list[object] = [max(1, min(scan_limit, MAX_AUDIT_SCAN_LIMIT))]
        if not viewer.global_access:
            visible_groups = sorted(viewer.group_paths)
            if not visible_groups:
                return []
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
        rows = self._execute_all(_audit_query(where_sql), tuple(params))
        return [_enriched_event_from_row(row) for row in rows]


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


def _audit_query(where_sql: str) -> str:
    return f"""
        WITH recent AS (
            SELECT *
            FROM audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT %s
        ),
        enriched AS (
            SELECT
                recent.id::text AS id,
                recent.event_type,
                recent.actor_id::text AS actor_id,
                recent.target_type,
                recent.target_id,
                recent.payload,
                recent.created_at,
                COALESCE(
                    actor.email,
                    CASE
                        WHEN recent.actor_id::text = recent.target_id THEN recent.payload->>'email'
                    END
                ) AS actor_email,
                CASE
                    WHEN recent.target_type = 'user' THEN COALESCE(target_user.email, recent.payload->>'email')
                END AS target_user_email,
                CASE
                    WHEN recent.target_type = 'user' THEN COALESCE(target_user.name, recent.payload->>'name')
                END AS target_user_name,
                CASE
                    WHEN recent.event_type LIKE 'auth.%%' THEN 'authentication'
                    WHEN recent.target_type = 'document'
                      OR recent.event_type LIKE 'upload.%%'
                      OR recent.event_type LIKE 'documents.%%'
                      OR recent.event_type LIKE 'folder_ingest.%%'
                      OR recent.event_type LIKE 'internal.document%%'
                      OR recent.event_type LIKE 'internal.supersession%%' THEN 'document'
                    WHEN recent.event_type LIKE 'ingest.%%'
                      OR recent.event_type LIKE 'internal.ingest.%%'
                      OR recent.event_type LIKE 'admin.ingest.%%' THEN 'ingestion'
                    WHEN recent.target_type = 'user'
                      OR recent.event_type LIKE 'admin.user.%%' THEN 'user'
                    WHEN recent.event_type LIKE 'review.%%' THEN 'review'
                    WHEN recent.event_type LIKE 'query.%%' THEN 'query'
                    ELSE 'system'
                END AS category,
                CASE
                    WHEN recent.target_type = 'document' THEN recent.target_id
                    ELSE recent.payload->>'doc_id'
                END AS doc_id,
                document.title AS doc_title,
                document.group_path AS doc_group_path,
                document.clearance_level AS doc_clearance_level,
                document.deleted_at AS doc_deleted_at
            FROM recent
            LEFT JOIN users actor ON actor.id = recent.actor_id
            LEFT JOIN users target_user ON recent.target_type = 'user' AND target_user.id::text = recent.target_id
            LEFT JOIN documents document
              ON document.id::text = CASE
                    WHEN recent.target_type = 'document' THEN recent.target_id
                    ELSE recent.payload->>'doc_id'
                 END
        )
        SELECT *
        FROM enriched
        WHERE {where_sql}
        ORDER BY created_at DESC, id DESC
    """


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
