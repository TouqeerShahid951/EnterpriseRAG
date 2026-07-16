"""Read-only audit trail routes."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from rag.auth.dependencies import require_current_user
from rag.auth.permissions import can_view_audit, is_global_admin
from rag.audit.models import (
    AUDIT_CATEGORIES,
    AuditEventWriter,
    AuditFilters,
    AuditRepository,
    AuditViewerScope,
    EnrichedAuditEvent,
    MAX_AUDIT_SCAN_LIMIT,
)
from rag.audit.repository import audit_repository_for
from rag.documents.repository import DocumentRepository, get_document_repository
from rag.auth.identity_models import IdentityRepository, UserRecord
from rag.auth.identity_repository import get_identity_repository
from rag.audit.schemas import AuditEvent, AuditEventListResponse, AuditSummary
from rag.shared.contracts.http import ErrorResponse
from rag.shared.contracts.group_paths import normalize_group_path

router = APIRouter(prefix="/audit-log", tags=["audit"])

AUDIT_SCAN_LIMIT = MAX_AUDIT_SCAN_LIMIT


def get_audit_repository(
    document_repo: DocumentRepository = Depends(get_document_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
) -> AuditRepository:
    return audit_repository_for(document_repo, identity_repo)


def get_audit_writer(
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> AuditEventWriter:
    return document_repo


def _audit_filters(
    search: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=40),
    event_type: str | None = Query(default=None, max_length=120),
    actor_id: str | None = Query(default=None, max_length=200),
    target_type: str | None = Query(default=None, max_length=80),
    target_id: str | None = Query(default=None, max_length=200),
    group_path: str | None = Query(default=None, max_length=240),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
) -> AuditFilters:
    return AuditFilters(
        search=(search or "").strip(),
        category=_normalized_category(category),
        event_type=(event_type or "").strip(),
        actor_query=(actor_id or "").strip().lower(),
        target_type=(target_type or "").strip(),
        target_id=(target_id or "").strip().lower(),
        group_path=_normalized_group_filter(group_path),
        created_from=created_from,
        created_to=created_to,
    )


@router.get(
    "",
    response_model=AuditEventListResponse,
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
    summary="List visible audit events",
)
async def list_audit_events(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserRecord = Depends(require_current_user),
    filters: AuditFilters = Depends(_audit_filters),
    repo: AuditRepository = Depends(get_audit_repository),
) -> AuditEventListResponse:
    _require_audit_viewer(user)
    page = await run_in_threadpool(
        repo.search_visible_events_page,
        filters=filters,
        viewer=_audit_viewer_scope(user),
        limit=limit,
        offset=offset,
    )
    return AuditEventListResponse(
        items=[_event_to_schema(event) for event in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
        summary=AuditSummary(**asdict(page.summary)),
    )


@router.get(
    "/export",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
    summary="Export visible audit events as CSV",
)
async def export_audit_events(
    max_rows: int = Query(AUDIT_SCAN_LIMIT, ge=1, le=AUDIT_SCAN_LIMIT),
    user: UserRecord = Depends(require_current_user),
    filters: AuditFilters = Depends(_audit_filters),
    repo: AuditRepository = Depends(get_audit_repository),
    writer: AuditEventWriter = Depends(get_audit_writer),
) -> Response:
    _require_audit_viewer(user)
    page = await run_in_threadpool(
        repo.search_visible_events_page,
        filters=filters,
        viewer=_audit_viewer_scope(user),
        limit=max_rows,
    )
    rows = list(page.items)
    await run_in_threadpool(
        writer.append_audit_event,
        event_type="audit.exported",
        actor_id=user.id,
        target_type="audit_log",
        target_id=None,
        payload={
            "filters": _filters_payload(filters),
            "row_count": len(rows),
            "matched_count": page.total,
            "truncated": len(rows) < page.total,
        },
    )
    return Response(
        content=_audit_events_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )


def _require_audit_viewer(user: UserRecord) -> None:
    if can_view_audit(user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "audit_viewer_required",
            "message": "Audit viewer account type required.",
        },
    )


def _audit_viewer_scope(user: UserRecord) -> AuditViewerScope:
    return AuditViewerScope(
        global_access=is_global_admin(user),
        group_paths=user.group_paths,
        clearance_level=user.clearance_level,
    )


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
        writer.writerow(
            {
                "id": record.id,
                "created_at": record.created_at.isoformat()
                if record.created_at
                else "",
                "event_type": record.event_type,
                "category": event.category,
                "actor_id": record.actor_id or "",
                "actor_email": event.actor_email or "",
                "target_type": record.target_type or "",
                "target_id": record.target_id or "",
                "target_user_email": event.target_user_email or "",
                "target_user_name": event.target_user_name or "",
                "target_document_title": event.target_document_title or "",
                "group_path": (
                    record.payload.get("group_path")
                    if isinstance(record.payload.get("group_path"), str)
                    else ""
                ),
                "summary": _event_export_summary(event),
                "payload_json": json.dumps(record.payload, sort_keys=True),
            }
        )
    return buffer.getvalue()


def _event_export_summary(event: EnrichedAuditEvent) -> str:
    record = event.record
    target = (
        event.target_user_email or record.target_id or record.target_type or "workspace"
    )
    if record.event_type == "auth.login":
        return "User signed in"
    if record.event_type == "admin.user.deleted":
        return f"Deleted user account {target}"
    if record.target_type == "document" or isinstance(
        record.payload.get("doc_id"), str
    ):
        document_title = event.target_document_title or target
        return f"{record.event_type} {document_title}"
    return f"{record.event_type} {target}"


def _filters_payload(filters: AuditFilters) -> dict[str, object]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value or None
        for key, value in asdict(filters).items()
    }


def _normalized_category(value: str | None) -> str | None:
    candidate = (value or "").strip().lower()
    if not candidate:
        return None
    if candidate not in AUDIT_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_audit_category",
                "message": "Audit category filter is not supported.",
            },
        )
    return candidate


def _normalized_group_filter(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return ""
    try:
        return normalize_group_path(candidate)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_audit_group", "message": str(exc)},
        ) from exc
