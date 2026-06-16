"""Read-only audit trail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...auth.dependencies import require_current_user
from ...auth.document_access import can_read_document
from ...auth.permissions import can_view_audit, is_global_admin, is_group_path_in_user_scope
from ...repositories.documents import AuditEventRecord, DocumentRepository, get_document_repository
from ...repositories.identity import UserRecord
from ...schemas.audit import AuditEvent, AuditEventListResponse
from ...schemas.common import ErrorResponse

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get(
    "",
    response_model=AuditEventListResponse,
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorResponse}},
    summary="List visible audit events",
)
async def list_audit_events(
    limit: int = Query(100, ge=1, le=500),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> AuditEventListResponse:
    if not can_view_audit(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "audit_viewer_required", "message": "Audit viewer account type required."},
        )
    visible = [event for event in repo.list_audit_events(limit=limit) if _audit_event_visible(user, event, repo)]
    return AuditEventListResponse(items=[_event_to_schema(event) for event in visible], total=len(visible))


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


def _event_to_schema(event: AuditEventRecord) -> AuditEvent:
    return AuditEvent(
        id=event.id,
        event_type=event.event_type,
        actor_id=event.actor_id,
        target_type=event.target_type,
        target_id=event.target_id,
        payload=event.payload,
        created_at=event.created_at,
    )
