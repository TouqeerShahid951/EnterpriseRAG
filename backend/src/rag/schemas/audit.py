from datetime import datetime
from typing import Any

from pydantic import Field

from .common import ContractModel


class AuditEvent(ContractModel):
    id: str
    event_type: str
    actor_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class AuditEventListResponse(ContractModel):
    items: list[AuditEvent] = Field(default_factory=list)
    total: int = Field(..., ge=0)
