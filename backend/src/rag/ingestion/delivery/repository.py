"""Persistence contract for atomic ingestion delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import (
    IngestDeliveryMutation,
    IngestOutboxRecord,
    IngestWorkerDeliveryClaim,
    PendingIngestDelivery,
)


class IngestDeliveryRepository(Protocol):
    def create_queued_job_with_delivery(
        self,
        delivery: PendingIngestDelivery,
        *,
        doc_id: str,
        origin: str,
        retry_of_job_id: str | None,
    ) -> IngestDeliveryMutation: ...

    def queue_existing_job_with_delivery(
        self,
        job_id: str,
        delivery: PendingIngestDelivery,
        *,
        expected_statuses: frozenset[str],
        increment_review_resume: bool,
    ) -> IngestDeliveryMutation: ...

    def recover_stale_job_with_delivery(
        self,
        job_id: str,
        delivery: PendingIngestDelivery,
        *,
        stale_before: datetime,
        max_failures: int,
    ) -> IngestDeliveryMutation: ...

    def record_worker_failure_with_delivery(
        self,
        job_id: str,
        *,
        run_token: str,
        max_failures: int,
        error_code: str,
        error_message_safe: str,
        delivery: PendingIngestDelivery | None,
    ) -> IngestDeliveryMutation: ...

    def claim_worker_delivery(
        self,
        job_id: str,
        *,
        delivery_id: str,
        run_token: str,
        max_failures: int,
    ) -> IngestWorkerDeliveryClaim: ...

    def claim_due_outbox(
        self,
        *,
        claim_token: str,
        limit: int,
        lease_seconds: int,
        now: datetime,
    ) -> tuple[IngestOutboxRecord, ...]: ...

    def ack_outbox_delivery(self, delivery_id: str, *, claim_token: str) -> bool: ...

    def release_outbox_delivery(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        available_at: datetime,
        error_code: str,
    ) -> bool: ...
