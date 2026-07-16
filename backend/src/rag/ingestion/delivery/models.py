"""Ingestion delivery records and operation results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from ..job_models import IngestJobRecord


@dataclass(frozen=True)
class PendingIngestDelivery:
    delivery_id: str
    job_id: str
    event_kind: str
    payload: dict[str, Any]
    available_at: datetime


@dataclass(frozen=True)
class IngestOutboxRecord:
    delivery_id: str
    job_id: str
    event_kind: str
    payload: dict[str, Any]
    available_at: datetime
    claim_token: str | None
    claim_expires_at: datetime | None
    publish_attempt_count: int
    published_at: datetime | None
    last_error_code: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class IngestDeliveryMutation:
    job: IngestJobRecord | None
    delivery: IngestOutboxRecord | None
    changed: bool
    exhausted: bool = False


WorkerDeliveryDisposition = Literal[
    "accepted",
    "missing",
    "busy",
    "duplicate",
    "exhausted",
]


@dataclass(frozen=True)
class IngestWorkerDeliveryClaim:
    job: IngestJobRecord | None
    claimed: bool
    disposition: WorkerDeliveryDisposition


@dataclass(frozen=True)
class IngestOutboxClaim:
    claim_token: str
    deliveries: tuple[IngestOutboxRecord, ...]


@dataclass(frozen=True)
class IngestDeliveryDispatchResult:
    claimed_ids: tuple[str, ...]
    published_ids: tuple[str, ...]
    released_ids: tuple[str, ...]

    @property
    def claimed_count(self) -> int:
        return len(self.claimed_ids)

    @property
    def published_count(self) -> int:
        return len(self.published_ids)

    @property
    def released_count(self) -> int:
        return len(self.released_ids)
