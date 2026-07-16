"""Audit query contracts shared by route and repository adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from ..shared.contracts.clearance import ClearanceLevel

MAX_AUDIT_SCAN_LIMIT = 5000
AUDIT_CATEGORIES = frozenset(
    {"authentication", "document", "ingestion", "user", "review", "query", "system"}
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
class AuditViewerScope:
    global_access: bool
    group_paths: tuple[str, ...]
    clearance_level: ClearanceLevel


@dataclass(frozen=True)
class AuditEventRecord:
    id: str
    event_type: str
    actor_id: str | None
    target_type: str | None
    target_id: str | None
    payload: dict[str, Any]
    created_at: datetime | None


@dataclass(frozen=True)
class EnrichedAuditEvent:
    record: AuditEventRecord
    category: str
    actor_email: str | None
    target_user_email: str | None
    target_user_name: str | None
    target_document_title: str | None


@dataclass(frozen=True)
class AuditSummaryRecord:
    total: int = 0
    document_events: int = 0
    auth_events: int = 0
    system_events: int = 0
    actor_count: int = 0
    event_type_count: int = 0
    category_counts: dict[str, int] = field(default_factory=dict)
    target_type_counts: dict[str, int] = field(default_factory=dict)
    event_type_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEventPage:
    items: tuple[EnrichedAuditEvent, ...] = ()
    total: int = 0
    summary: AuditSummaryRecord = field(default_factory=AuditSummaryRecord)


class AuditEventWriter(Protocol):
    def append_audit_event(
        self,
        *,
        event_type: str,
        actor_id: str | None,
        target_type: str | None,
        target_id: str | None,
        payload: dict[str, Any],
    ) -> None: ...


class AuditRepository(Protocol):
    def search_visible_events_page(
        self,
        *,
        filters: AuditFilters,
        viewer: AuditViewerScope,
        limit: int,
        offset: int = 0,
    ) -> AuditEventPage: ...

    def search_visible_events(
        self,
        *,
        filters: AuditFilters,
        viewer: AuditViewerScope,
        scan_limit: int,
    ) -> list[EnrichedAuditEvent]: ...


def audit_event_category(event: AuditEventRecord) -> str:
    event_type = event.event_type
    if event_type.startswith("auth."):
        return "authentication"
    if event.target_type == "document" or event_type.startswith(
        (
            "upload.",
            "documents.",
            "folder_ingest.",
            "internal.document",
            "internal.supersession",
        )
    ):
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


def payload_document_title(payload: dict[str, Any]) -> str | None:
    for key in (
        "document_title",
        "target_document_title",
        "document_name",
        "title",
        "filename",
    ):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None
