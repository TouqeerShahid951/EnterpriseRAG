from datetime import datetime
from typing import Any

from pydantic import Field

from rag.shared.contracts.http import ContractModel


class AuditEvent(ContractModel):
    id: str
    event_type: str
    actor_id: str | None = None
    actor_email: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_user_email: str | None = None
    target_user_name: str | None = None
    target_document_title: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class AuditSummary(ContractModel):
    total: int = Field(0, ge=0)
    document_events: int = Field(0, ge=0)
    auth_events: int = Field(0, ge=0)
    system_events: int = Field(0, ge=0)
    actor_count: int = Field(0, ge=0)
    event_type_count: int = Field(0, ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)
    target_type_counts: dict[str, int] = Field(default_factory=dict)
    event_type_counts: dict[str, int] = Field(default_factory=dict)


class AuditEventListResponse(ContractModel):
    items: list[AuditEvent] = Field(default_factory=list)
    total: int = Field(..., ge=0)
    limit: int = Field(100, ge=1)
    offset: int = Field(0, ge=0)
    summary: AuditSummary = Field(default_factory=AuditSummary)
