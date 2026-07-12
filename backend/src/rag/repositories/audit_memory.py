"""Repository-backed audit queries for memory and test adapters."""

from __future__ import annotations

from typing import Any

from ..auth.abac import normalize_group_path
from ..shared.contracts.clearance import can_access_clearance
from .audit_models import (
    AuditFilters,
    AuditViewerScope,
    EnrichedAuditEvent,
    MAX_AUDIT_SCAN_LIMIT,
    audit_event_category,
    payload_document_title,
)
from .document_models import AuditEventRecord, DocumentRecord, DocumentRepository
from .identity_models import IdentityRepository


class RepositoryAuditRepository:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        identities: IdentityRepository,
    ) -> None:
        self._documents = documents
        self._identities = identities

    def search_visible_events(
        self,
        *,
        filters: AuditFilters,
        viewer: AuditViewerScope,
        scan_limit: int,
    ) -> list[EnrichedAuditEvent]:
        matches: list[EnrichedAuditEvent] = []
        viewer_groups = {normalize_group_path(path) for path in viewer.group_paths}
        limit = max(1, min(scan_limit, MAX_AUDIT_SCAN_LIMIT))
        for record in self._documents.list_audit_events(limit=limit):
            document_id = (
                record.target_id
                if record.target_type == "document"
                else record.payload.get("doc_id")
            )
            document_id = document_id if isinstance(document_id, str) else None
            document = (
                self._documents.get_document(document_id, include_deleted=True)
                if document_id is not None
                else None
            )
            if not _event_is_visible(
                record, document_id, document, viewer, viewer_groups
            ):
                continue
            event = self._enrich(record, document)
            if _matches_filters(event, document, filters):
                matches.append(event)
        return matches

    def _enrich(
        self,
        record: AuditEventRecord,
        document: DocumentRecord | None,
    ) -> EnrichedAuditEvent:
        actor = (
            self._identities.get_user_by_id(record.actor_id)
            if record.actor_id
            else None
        )
        target_user = (
            self._identities.get_user_by_id(record.target_id)
            if record.target_type == "user" and record.target_id
            else None
        )
        payload_email = record.payload.get("email")
        payload_name = record.payload.get("name")
        actor_email = actor.email if actor else None
        if actor is None and record.actor_id and record.actor_id == record.target_id:
            actor_email = payload_email if isinstance(payload_email, str) else None
        target_email = target_user.email if target_user else None
        target_name = target_user.name if target_user else None
        if target_user is None and record.target_type == "user":
            target_email = payload_email if isinstance(payload_email, str) else None
            target_name = payload_name if isinstance(payload_name, str) else None
        document_title = (
            document.title.strip()
            if document is not None and document.title and document.title.strip()
            else payload_document_title(record.payload)
        )
        return EnrichedAuditEvent(
            record=record,
            category=audit_event_category(record),
            actor_email=actor_email,
            target_user_email=target_email,
            target_user_name=target_name,
            target_document_title=document_title,
        )


def _event_is_visible(
    event: AuditEventRecord,
    document_id: str | None,
    document: DocumentRecord | None,
    viewer: AuditViewerScope,
    viewer_groups: set[str],
) -> bool:
    if viewer.global_access:
        return True
    if document_id is not None:
        return (
            document is not None
            and document.deleted_at is None
            and can_access_clearance(
                viewer.clearance_level,
                document.clearance_level,
            )
            and any(
                normalize_group_path(path) in viewer_groups
                for path in document.access_group_paths
            )
        )
    group_path = event.payload.get("group_path")
    return (
        isinstance(group_path, str)
        and normalize_group_path(group_path) in viewer_groups
    )


def _matches_filters(
    event: EnrichedAuditEvent,
    document: DocumentRecord | None,
    filters: AuditFilters,
) -> bool:
    record = event.record
    exact_filters = (
        (filters.category, event.category),
        (filters.event_type, record.event_type),
        (filters.target_type, record.target_type),
    )
    if any(expected and expected != actual for expected, actual in exact_filters):
        return False
    if filters.actor_query and not (
        filters.actor_query in (record.actor_id or "").lower()
        or filters.actor_query in (event.actor_email or "").lower()
    ):
        return False
    if filters.target_id and filters.target_id not in (record.target_id or "").lower():
        return False
    if filters.group_path:
        payload_group = record.payload.get("group_path")
        candidate_groups = [payload_group] if isinstance(payload_group, str) else []
        if document is not None:
            candidate_groups.append(document.group_path)
        if not any(
            _is_group_or_descendant(group, filters.group_path)
            for group in candidate_groups
        ):
            return False
    if filters.created_from and (
        record.created_at is None or record.created_at < filters.created_from
    ):
        return False
    if filters.created_to and (
        record.created_at is None or record.created_at > filters.created_to
    ):
        return False
    if not filters.search:
        return True
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
    if document is not None:
        haystack.extend(
            [document.title or "", document.group_path, document.clearance_level]
        )
    query = filters.search.lower()
    return any(query in value.lower() for value in haystack)


def _is_group_or_descendant(candidate: str, group_path: str) -> bool:
    candidate = normalize_group_path(candidate)
    group_path = normalize_group_path(group_path)
    return candidate == group_path or candidate.startswith(f"{group_path}/")


def _payload_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, list):
            value = " ".join(str(item) for item in value[:20])
        elif isinstance(value, dict):
            value = " ".join(str(item) for item in value.values())
        elif not isinstance(value, (str, int, float, bool)) and value is not None:
            continue
        parts.append(f"{key} {value}")
    return " ".join(parts)
