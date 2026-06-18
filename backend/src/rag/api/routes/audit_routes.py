"""Read-only audit trail routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...auth.dependencies import require_current_user
from ...auth.document_access import can_read_document
from ...auth.permissions import can_view_audit, is_global_admin, is_group_path_in_user_scope
from ...repositories.documents import AuditEventRecord, DocumentRepository, get_document_repository
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...schemas.audit import AuditEvent, AuditEventListResponse, AuditSummary
from ...schemas.common import ErrorResponse

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
    if not can_view_audit(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "audit_viewer_required", "message": "Audit viewer account type required."},
        )
    filters = AuditFilters(
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
    enriched = [
        _enrich_event(event, identity_repo)
        for event in repo.list_audit_events(limit=max(AUDIT_SCAN_LIMIT, offset + limit))
        if _audit_event_visible(user, event, repo)
    ]
    matching = [event for event in enriched if _matches_filters(event, filters, repo)]
    page = matching[offset:offset + limit]
    return AuditEventListResponse(
        items=[_event_to_schema(event) for event in page],
        total=len(matching),
        limit=limit,
        offset=offset,
        summary=_summary(matching),
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
        payload=record.payload,
        created_at=record.created_at,
    )


def _enrich_event(event: AuditEventRecord, repo: IdentityRepository) -> EnrichedAuditEvent:
    actor = repo.get_user_by_id(event.actor_id) if event.actor_id else None
    target_user = repo.get_user_by_id(event.target_id) if event.target_type == "user" and event.target_id else None
    payload_email = event.payload.get("email")
    payload_name = event.payload.get("name")
    actor_payload_email = payload_email if event.actor_id and event.actor_id == event.target_id and isinstance(payload_email, str) else None
    return EnrichedAuditEvent(
        record=event,
        category=_event_category(event),
        actor_email=actor.email if actor else actor_payload_email,
        target_user_email=target_user.email if target_user else payload_email if event.target_type == "user" and isinstance(payload_email, str) else None,
        target_user_name=target_user.name if target_user else payload_name if event.target_type == "user" and isinstance(payload_name, str) else None,
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
        event.category,
        _payload_text(record.payload),
    ]
    doc_id = record.target_id if record.target_type == "document" else record.payload.get("doc_id")
    if isinstance(doc_id, str):
        document = repo.get_document(doc_id, include_deleted=True)
        if document is not None:
            haystack.extend([document.title, document.group_path, document.clearance_level])
    return any(query in value.lower() for value in haystack)


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
