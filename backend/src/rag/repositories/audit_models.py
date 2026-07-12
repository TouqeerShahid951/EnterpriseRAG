"""Audit query contracts shared by route and repository adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from ..shared.contracts.clearance import ClearanceLevel
from .document_models import AuditEventRecord

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
class EnrichedAuditEvent:
    record: AuditEventRecord
    category: str
    actor_email: str | None
    target_user_email: str | None
    target_user_name: str | None
    target_document_title: str | None


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
    def search_visible_events(
        self,
        *,
        filters: AuditFilters,
        viewer: AuditViewerScope,
        scan_limit: int,
    ) -> list[EnrichedAuditEvent]: ...


def audit_event_from_row(row: dict[str, Any]) -> AuditEventRecord:
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    return AuditEventRecord(
        id=str(row["id"]),
        event_type=str(row["event_type"]),
        actor_id=str(row["actor_id"]) if row.get("actor_id") is not None else None,
        target_type=str(row["target_type"])
        if row.get("target_type") is not None
        else None,
        target_id=str(row["target_id"]) if row.get("target_id") is not None else None,
        payload=dict(payload),
        created_at=row.get("created_at"),
    )


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
