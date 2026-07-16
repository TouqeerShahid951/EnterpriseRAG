"""Repository-backed audit queries for memory and test adapters."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ...auth.abac import normalize_group_path
from ...auth.identity_models import IdentityRepository
from ...documents.models import (
    AuditEventRecord,
    DocumentRecord,
    DocumentRepository,
)
from ...shared.contracts.clearance import can_access_clearance
from ..models import (
    AuditEventPage,
    AuditFilters,
    AuditSummaryRecord,
    AuditViewerScope,
    EnrichedAuditEvent,
    MAX_AUDIT_SCAN_LIMIT,
    audit_event_category,
    payload_document_title,
)


class RepositoryAuditRepository:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        identities: IdentityRepository,
    ) -> None:
        self._documents = documents
        self._identities = identities

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
        matches = self._matching_visible_events(
            filters=filters,
            viewer=viewer,
            scan_limit=MAX_AUDIT_SCAN_LIMIT,
        )
        return AuditEventPage(
            items=tuple(matches[offset : offset + limit]),
            total=len(matches),
            summary=_summarize_events(matches),
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

    def _matching_visible_events(
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


def _summarize_events(events: list[EnrichedAuditEvent]) -> AuditSummaryRecord:
    category_counts = Counter(event.category for event in events)
    event_type_counts = Counter(event.record.event_type for event in events)
    target_type_counts = Counter(
        event.record.target_type or "workspace" for event in events
    )
    return AuditSummaryRecord(
        total=len(events),
        document_events=sum(
            1
            for event in events
            if event.record.target_type == "document"
            or isinstance(event.record.payload.get("doc_id"), str)
            or event.category == "document"
        ),
        auth_events=category_counts.get("authentication", 0),
        system_events=sum(1 for event in events if event.record.actor_id is None),
        actor_count=len(
            {event.record.actor_id for event in events if event.record.actor_id}
        ),
        event_type_count=len(event_type_counts),
        category_counts=dict(category_counts),
        target_type_counts=dict(target_type_counts),
        event_type_counts=dict(event_type_counts),
    )
