"""Read-only audit trail routes."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from ...auth.dependencies import require_current_user
from ...auth.document_access import can_read_document
from ...auth.permissions import can_view_audit, is_global_admin, is_group_path_in_user_scope
from ...repositories.document_postgres import PostgresDocumentRepository, audit_event_from_row
from ...repositories.documents import AuditEventRecord, DocumentRepository, get_document_repository
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...schemas.audit import AuditEvent, AuditEventListResponse, AuditSummary
from ...schemas.common import ErrorResponse
from ...shared.contracts.clearance import clearance_levels_at_or_below

router = APIRouter(prefix="/audit-log", tags=["audit"])

AUDIT_SCAN_LIMIT = 5000
CATEGORIES = {"authentication", "document", "ingestion", "user", "review", "query", "system"}


@router.get(
    "",
    response_model=AuditEventListResponse,
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
    summary="List visible audit events",
)
async def list_audit_events(
    search: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=40),
    event_type: str | None = Query(default=None, max_length=120),
    actor_id: str | None = Query(default=None, max_length=200),
    target_type: str | None = Query(default=None, max_length=80),
    target_id: str | None = Query(default=None, max_length=200),
    group_path: str | None = Query(default=None, max_length=240),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
) -> AuditEventListResponse:
    filters = _audit_filters(
        search=search,
        category=category,
        event_type=event_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        group_path=group_path,
        created_from=created_from,
        created_to=created_to,
    )
    matching = _postgres_filtered_audit_events(
        filters=filters,
        user=user,
        repo=repo,
        scan_limit=max(AUDIT_SCAN_LIMIT, offset + limit),
    )
    if matching is None:
        matching = _filtered_audit_events(
            filters=filters,
            user=user,
            repo=repo,
            identity_repo=identity_repo,
            scan_limit=max(AUDIT_SCAN_LIMIT, offset + limit),
        )
    page = matching[offset:offset + limit]
    return AuditEventListResponse(
        items=[_event_to_schema(event) for event in page],
        total=len(matching),
        limit=limit,
        offset=offset,
        summary=_summary(matching),
    )


@router.get(
    "/export",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
    summary="Export visible audit events as CSV",
)
async def export_audit_events(
    search: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=40),
    event_type: str | None = Query(default=None, max_length=120),
    actor_id: str | None = Query(default=None, max_length=200),
    target_type: str | None = Query(default=None, max_length=80),
    target_id: str | None = Query(default=None, max_length=200),
    group_path: str | None = Query(default=None, max_length=240),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    max_rows: int = Query(AUDIT_SCAN_LIMIT, ge=1, le=AUDIT_SCAN_LIMIT),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
) -> Response:
    filters = _audit_filters(
        search=search,
        category=category,
        event_type=event_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        group_path=group_path,
        created_from=created_from,
        created_to=created_to,
    )
    matching = _postgres_filtered_audit_events(
        filters=filters,
        user=user,
        repo=repo,
        scan_limit=AUDIT_SCAN_LIMIT,
    )
    if matching is None:
        matching = _filtered_audit_events(
            filters=filters,
            user=user,
            repo=repo,
            identity_repo=identity_repo,
            scan_limit=AUDIT_SCAN_LIMIT,
        )
    rows = matching[:max_rows]
    repo.append_audit_event(
        event_type="audit.exported",
        actor_id=user.id,
        target_type="audit_log",
        target_id=None,
        payload={
            "filters": _filters_payload(filters),
            "row_count": len(rows),
            "matched_count": len(matching),
            "truncated": len(rows) < len(matching),
        },
    )
    return Response(
        content=_audit_events_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )


@dataclass(frozen=True)
class AuditFilters:
    search: str
    category: str | None
    event_type: str
    actor_query: str
    target_type: str
    target_id: str
    group_path: str
    created_from: datetime | None
    created_to: datetime | None


@dataclass(frozen=True)
class EnrichedAuditEvent:
    record: AuditEventRecord
    category: str
    actor_email: str | None
    target_user_email: str | None
    target_user_name: str | None
    target_document_title: str | None


def _audit_filters(
    *,
    search: str | None,
    category: str | None,
    event_type: str | None,
    actor_id: str | None,
    target_type: str | None,
    target_id: str | None,
    group_path: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
) -> AuditFilters:
    return AuditFilters(
        search=(search or "").strip(),
        category=_normalized_category(category),
        event_type=(event_type or "").strip(),
        actor_query=(actor_id or "").strip().lower(),
        target_type=(target_type or "").strip(),
        target_id=(target_id or "").strip().lower(),
        group_path=(group_path or "").strip(),
        created_from=created_from,
        created_to=created_to,
    )


def _filtered_audit_events(
    *,
    filters: AuditFilters,
    user: UserRecord,
    repo: DocumentRepository,
    identity_repo: IdentityRepository,
    scan_limit: int,
) -> list[EnrichedAuditEvent]:
    if not can_view_audit(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "audit_viewer_required", "message": "Audit viewer account type required."},
        )
    enriched = [
        _enrich_event(event, identity_repo, repo)
        for event in repo.list_audit_events(limit=scan_limit)
        if _audit_event_visible(user, event, repo)
    ]
    return [event for event in enriched if _matches_filters(event, filters, repo)]


def _postgres_filtered_audit_events(
    *,
    filters: AuditFilters,
    user: UserRecord,
    repo: DocumentRepository,
    scan_limit: int,
) -> list[EnrichedAuditEvent] | None:
    if not isinstance(repo, PostgresDocumentRepository):
        return None
    if not can_view_audit(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "audit_viewer_required", "message": "Audit viewer account type required."},
        )

    clauses: list[str] = []
    params: list[object] = [max(1, min(scan_limit, AUDIT_SCAN_LIMIT))]
    if not is_global_admin(user):
        visible_groups = sorted(user.group_paths)
        if not visible_groups:
            return []
        allowed_clearances = list(clearance_levels_at_or_below(user.clearance_level))
        clauses.append(
            """
            (
                payload->>'group_path' = ANY(%s::text[])
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
        params.extend([visible_groups, allowed_clearances, visible_groups, visible_groups])
    if filters.category:
        clauses.append("category = %s")
        params.append(filters.category)
    if filters.event_type:
        clauses.append("event_type = %s")
        params.append(filters.event_type)
    if filters.actor_query:
        clauses.append("(lower(COALESCE(actor_id, '')) LIKE %s OR lower(COALESCE(actor_email, '')) LIKE %s)")
        actor_pattern = f"%{filters.actor_query}%"
        params.extend([actor_pattern, actor_pattern])
    if filters.target_type:
        clauses.append("target_type = %s")
        params.append(filters.target_type)
    if filters.target_id:
        clauses.append("lower(COALESCE(target_id, '')) LIKE %s")
        params.append(f"%{filters.target_id}%")
    if filters.group_path:
        group = _normalized_group_filter(filters.group_path)
        clauses.append(
            """
            (
                payload->>'group_path' = %s
                OR payload->>'group_path' LIKE %s
                OR doc_group_path = %s
                OR doc_group_path LIKE %s
            )
            """
        )
        params.extend([group, f"{group}/%", group, f"{group}/%"])
    if filters.created_from:
        clauses.append("created_at >= %s")
        params.append(filters.created_from)
    if filters.created_to:
        clauses.append("created_at <= %s")
        params.append(filters.created_to)
    if filters.search:
        pattern = f"%{filters.search.lower()}%"
        clauses.append(
            """
            (
                lower(id) LIKE %s
                OR lower(event_type) LIKE %s
                OR lower(COALESCE(actor_id, '')) LIKE %s
                OR lower(COALESCE(actor_email, '')) LIKE %s
                OR lower(COALESCE(target_type, '')) LIKE %s
                OR lower(COALESCE(target_id, '')) LIKE %s
                OR lower(COALESCE(target_user_email, '')) LIKE %s
                OR lower(COALESCE(target_user_name, '')) LIKE %s
                OR lower(category) LIKE %s
                OR lower(COALESCE(payload::text, '')) LIKE %s
                OR lower(COALESCE(doc_title, '')) LIKE %s
                OR lower(COALESCE(doc_group_path, '')) LIKE %s
                OR lower(COALESCE(doc_clearance_level, '')) LIKE %s
            )
            """
        )
        params.extend([pattern] * 13)

    where_sql = " AND ".join(f"({clause})" for clause in clauses) if clauses else "TRUE"
    rows = repo._execute_all(
        f"""
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
        """,
        tuple(params),
    )
    return [_enriched_audit_event_from_row(row) for row in rows]


def _enriched_audit_event_from_row(row: dict[str, object]) -> EnrichedAuditEvent:
    record = audit_event_from_row(row)
    return EnrichedAuditEvent(
        record=record,
        category=str(row["category"]),
        actor_email=str(row["actor_email"]) if row.get("actor_email") else None,
        target_user_email=str(row["target_user_email"]) if row.get("target_user_email") else None,
        target_user_name=str(row["target_user_name"]) if row.get("target_user_name") else None,
        target_document_title=_text_or_none(row.get("doc_title")) or _payload_document_title(record.payload),
    )


def _audit_event_visible(user: UserRecord, event: AuditEventRecord, repo: DocumentRepository) -> bool:
    if is_global_admin(user):
        return True
    group_path = event.payload.get("group_path")
    if isinstance(group_path, str) and is_group_path_in_user_scope(user, group_path):
        return True
    doc_id = event.target_id if event.target_type == "document" else event.payload.get("doc_id")
    if isinstance(doc_id, str):
        document = repo.get_document(doc_id)
        return document is not None and can_read_document(user, document)
    return False


def _event_to_schema(event: EnrichedAuditEvent) -> AuditEvent:
    record = event.record
    return AuditEvent(
        id=record.id,
        event_type=record.event_type,
        actor_id=record.actor_id,
        actor_email=event.actor_email,
        target_type=record.target_type,
        target_id=record.target_id,
        target_user_email=event.target_user_email,
        target_user_name=event.target_user_name,
        target_document_title=event.target_document_title,
        payload=record.payload,
        created_at=record.created_at,
    )


def _enrich_event(event: AuditEventRecord, identity_repo: IdentityRepository, document_repo: DocumentRepository) -> EnrichedAuditEvent:
    actor = identity_repo.get_user_by_id(event.actor_id) if event.actor_id else None
    target_user = identity_repo.get_user_by_id(event.target_id) if event.target_type == "user" and event.target_id else None
    payload_email = event.payload.get("email")
    payload_name = event.payload.get("name")
    actor_payload_email = payload_email if event.actor_id and event.actor_id == event.target_id and isinstance(payload_email, str) else None
    return EnrichedAuditEvent(
        record=event,
        category=_event_category(event),
        actor_email=actor.email if actor else actor_payload_email,
        target_user_email=target_user.email if target_user else payload_email if event.target_type == "user" and isinstance(payload_email, str) else None,
        target_user_name=target_user.name if target_user else payload_name if event.target_type == "user" and isinstance(payload_name, str) else None,
        target_document_title=_document_title_for_event(event, document_repo),
    )


def _matches_filters(event: EnrichedAuditEvent, filters: AuditFilters, repo: DocumentRepository) -> bool:
    record = event.record
    if filters.category and event.category != filters.category:
        return False
    if filters.event_type and record.event_type != filters.event_type:
        return False
    if filters.actor_query and not _matches_actor(event, filters.actor_query):
        return False
    if filters.target_type and record.target_type != filters.target_type:
        return False
    if filters.target_id and filters.target_id not in (record.target_id or "").lower():
        return False
    if filters.group_path and not _matches_group_filter(record, filters.group_path, repo):
        return False
    if filters.created_from and (record.created_at is None or record.created_at < filters.created_from):
        return False
    if filters.created_to and (record.created_at is None or record.created_at > filters.created_to):
        return False
    if filters.search and not _matches_search(event, filters.search.lower(), repo):
        return False
    return True


def _matches_actor(event: EnrichedAuditEvent, query: str) -> bool:
    return query in (event.record.actor_id or "").lower() or query in (event.actor_email or "").lower()


def _matches_group_filter(event: AuditEventRecord, group_path: str, repo: DocumentRepository) -> bool:
    event_group = event.payload.get("group_path")
    if isinstance(event_group, str) and _group_equal_or_descendant(event_group, group_path):
        return True
    doc_id = event.target_id if event.target_type == "document" else event.payload.get("doc_id")
    if isinstance(doc_id, str):
        document = repo.get_document(doc_id, include_deleted=True)
        return document is not None and _group_equal_or_descendant(document.group_path, group_path)
    return False


def _matches_search(event: EnrichedAuditEvent, query: str, repo: DocumentRepository) -> bool:
    record = event.record
    haystack = [
        record.id,
        record.event_type,
        record.actor_id or "",
        event.actor_email or "",
        record.target_type or "",
        record.target_id or "",
        event.target_user_email or "",
        event.target_user_name or "",
        event.target_document_title or "",
        event.category,
        _payload_text(record.payload),
    ]
    doc_id = record.target_id if record.target_type == "document" else record.payload.get("doc_id")
    if isinstance(doc_id, str):
        document = repo.get_document(doc_id, include_deleted=True)
        if document is not None:
            haystack.extend([document.title, document.group_path, document.clearance_level])
    return any(query in value.lower() for value in haystack)


def _document_title_for_event(event: AuditEventRecord, repo: DocumentRepository) -> str | None:
    doc_id = event.target_id if event.target_type == "document" else event.payload.get("doc_id")
    if isinstance(doc_id, str):
        document = repo.get_document(doc_id, include_deleted=True)
        if document is not None:
            title = _text_or_none(document.title)
            if title:
                return title
    return _payload_document_title(event.payload)


def _payload_document_title(payload: dict[str, object]) -> str | None:
    for key in ("document_title", "target_document_title", "document_name", "title", "filename"):
        value = payload.get(key)
        text = _text_or_none(value)
        if text:
            return text
    return None


def _text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _payload_text(payload: dict[str, object]) -> str:
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            parts.append(f"{key} {value}")
        elif isinstance(value, list):
            parts.append(f"{key} {' '.join(str(item) for item in value[:20])}")
        elif isinstance(value, dict):
            parts.append(f"{key} {' '.join(str(item) for item in value.values())}")
    return " ".join(parts)


def _summary(events: list[EnrichedAuditEvent]) -> AuditSummary:
    category_counts: dict[str, int] = {}
    target_type_counts: dict[str, int] = {}
    event_type_counts: dict[str, int] = {}
    actors: set[str] = set()
    for event in events:
        record = event.record
        category_counts[event.category] = category_counts.get(event.category, 0) + 1
        event_type_counts[record.event_type] = event_type_counts.get(record.event_type, 0) + 1
        target_key = record.target_type or "workspace"
        target_type_counts[target_key] = target_type_counts.get(target_key, 0) + 1
        if record.actor_id:
            actors.add(record.actor_id)
    return AuditSummary(
        total=len(events),
        document_events=sum(1 for event in events if _is_document_event(event.record)),
        auth_events=category_counts.get("authentication", 0),
        system_events=sum(1 for event in events if event.record.actor_id is None),
        actor_count=len(actors),
        event_type_count=len(event_type_counts),
        category_counts=category_counts,
        target_type_counts=target_type_counts,
        event_type_counts=event_type_counts,
    )


def _audit_events_csv(events: list[EnrichedAuditEvent]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "id",
            "created_at",
            "event_type",
            "category",
            "actor_id",
            "actor_email",
            "target_type",
            "target_id",
            "target_user_email",
            "target_user_name",
            "target_document_title",
            "group_path",
            "summary",
            "payload_json",
        ],
    )
    writer.writeheader()
    for event in events:
        record = event.record
        writer.writerow({
            "id": record.id,
            "created_at": record.created_at.isoformat() if record.created_at else "",
            "event_type": record.event_type,
            "category": event.category,
            "actor_id": record.actor_id or "",
            "actor_email": event.actor_email or "",
            "target_type": record.target_type or "",
            "target_id": record.target_id or "",
            "target_user_email": event.target_user_email or "",
            "target_user_name": event.target_user_name or "",
            "target_document_title": event.target_document_title or "",
            "group_path": record.payload.get("group_path") if isinstance(record.payload.get("group_path"), str) else "",
            "summary": _event_export_summary(event),
            "payload_json": json.dumps(record.payload, sort_keys=True),
        })
    return buffer.getvalue()


def _event_export_summary(event: EnrichedAuditEvent) -> str:
    record = event.record
    target = event.target_user_email or record.target_id or record.target_type or "workspace"
    if record.event_type == "auth.login":
        return "User signed in"
    if record.event_type == "admin.user.deleted":
        return f"Deleted user account {target}"
    if record.target_type == "document" or isinstance(record.payload.get("doc_id"), str):
        document_title = event.target_document_title or target
        return f"{record.event_type} {document_title}"
    return f"{record.event_type} {target}"


def _filters_payload(filters: AuditFilters) -> dict[str, object]:
    return {
        "search": filters.search or None,
        "category": filters.category,
        "event_type": filters.event_type or None,
        "actor_query": filters.actor_query or None,
        "target_type": filters.target_type or None,
        "target_id": filters.target_id or None,
        "group_path": filters.group_path or None,
        "created_from": filters.created_from.isoformat() if filters.created_from else None,
        "created_to": filters.created_to.isoformat() if filters.created_to else None,
    }


def _is_document_event(event: AuditEventRecord) -> bool:
    return event.target_type == "document" or isinstance(event.payload.get("doc_id"), str) or _event_category(event) == "document"


def _event_category(event: AuditEventRecord) -> str:
    event_type = event.event_type
    if event_type.startswith("auth."):
        return "authentication"
    if event.target_type == "document" or event_type.startswith(("upload.", "documents.", "folder_ingest.", "internal.document", "internal.supersession")):
        return "document"
    if event_type.startswith(("ingest.", "internal.ingest.", "admin.ingest.")):
        return "ingestion"
    if event.target_type == "user" or event_type.startswith("admin.user."):
        return "user"
    if event_type.startswith("review."):
        return "review"
    if event_type.startswith("query."):
        return "query"
    return "system"


def _normalized_category(value: str | None) -> str | None:
    candidate = (value or "").strip().lower()
    if not candidate:
        return None
    if candidate not in CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_audit_category", "message": "Audit category filter is not supported."},
        )
    return candidate


def _group_equal_or_descendant(candidate: str, group_path: str) -> bool:
    normalized_candidate = "/" + candidate.strip().strip("/")
    normalized_filter = "/" + group_path.strip().strip("/")
    return normalized_candidate == normalized_filter or normalized_candidate.startswith(f"{normalized_filter}/")


def _normalized_group_filter(group_path: str) -> str:
    return "/" + group_path.strip().strip("/")
