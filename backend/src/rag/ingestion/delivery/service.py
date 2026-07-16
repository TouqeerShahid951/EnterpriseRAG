"""Application behavior for durable ingestion deliveries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from ..contracts import IngestJobPayload
from ..queue import IngestQueue
from .models import (
    IngestDeliveryDispatchResult,
    IngestDeliveryMutation,
    IngestOutboxClaim,
    IngestWorkerDeliveryClaim,
    PendingIngestDelivery,
)
from .repository import IngestDeliveryRepository


class IngestDeliveryService:
    def __init__(self, repository: IngestDeliveryRepository) -> None:
        self._repository = repository

    def create_queued_job(
        self,
        message: IngestJobPayload,
        *,
        origin: str,
        retry_of_job_id: str | None = None,
        event_kind: str = "initial",
        delivery_id: str | None = None,
        available_at: datetime | None = None,
    ) -> IngestDeliveryMutation:
        delivery = _pending_delivery(
            message,
            event_kind=event_kind,
            delivery_id=delivery_id,
            available_at=available_at,
        )
        return self._repository.create_queued_job_with_delivery(
            delivery,
            doc_id=message.doc_id,
            origin=origin,
            retry_of_job_id=retry_of_job_id,
        )

    def queue_existing_job(
        self,
        job_id: str,
        message: IngestJobPayload,
        *,
        expected_statuses: frozenset[str],
        event_kind: str,
        increment_review_resume: bool = False,
        delivery_id: str | None = None,
        available_at: datetime | None = None,
    ) -> IngestDeliveryMutation:
        _require_job_id(message, job_id)
        delivery = _pending_delivery(
            message,
            event_kind=event_kind,
            delivery_id=delivery_id,
            available_at=available_at,
        )
        return self._repository.queue_existing_job_with_delivery(
            job_id,
            delivery,
            expected_statuses=expected_statuses,
            increment_review_resume=increment_review_resume,
        )

    def recover_stale_job(
        self,
        job_id: str,
        message: IngestJobPayload,
        *,
        stale_before: datetime,
        max_failures: int,
        event_kind: str = "stale_recovery",
        delivery_id: str | None = None,
        available_at: datetime | None = None,
    ) -> IngestDeliveryMutation:
        _require_job_id(message, job_id)
        _require_positive(max_failures, "max_failures")
        delivery = _pending_delivery(
            message,
            event_kind=event_kind,
            delivery_id=delivery_id,
            available_at=available_at,
        )
        return self._repository.recover_stale_job_with_delivery(
            job_id,
            delivery,
            stale_before=_aware(stale_before, "stale_before"),
            max_failures=max_failures,
        )

    def record_worker_failure(
        self,
        job_id: str,
        *,
        run_token: str,
        max_failures: int,
        error_code: str,
        error_message_safe: str,
        retry_message: IngestJobPayload | None = None,
        event_kind: str = "worker_retry",
        delivery_id: str | None = None,
        available_at: datetime | None = None,
    ) -> IngestDeliveryMutation:
        _require_nonblank(run_token, "run_token")
        _require_nonblank(error_code, "error_code")
        _require_positive(max_failures, "max_failures")
        if retry_message is None:
            if delivery_id is not None:
                raise ValueError("delivery_id requires retry_message")
            delivery = None
        else:
            _require_job_id(retry_message, job_id)
            delivery = _pending_delivery(
                retry_message,
                event_kind=event_kind,
                delivery_id=delivery_id,
                available_at=available_at,
            )
        return self._repository.record_worker_failure_with_delivery(
            job_id,
            run_token=run_token,
            max_failures=max_failures,
            error_code=error_code.strip(),
            error_message_safe=error_message_safe,
            delivery=delivery,
        )

    def claim_worker_delivery(
        self,
        job_id: str,
        *,
        delivery_id: str,
        run_token: str,
        max_failures: int,
    ) -> IngestWorkerDeliveryClaim:
        _require_positive(max_failures, "max_failures")
        return self._repository.claim_worker_delivery(
            job_id,
            delivery_id=_uuid(delivery_id, "delivery_id"),
            run_token=_require_nonblank(run_token, "run_token"),
            max_failures=max_failures,
        )

    def claim_due(
        self,
        *,
        limit: int,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> IngestOutboxClaim:
        _require_positive(limit, "limit")
        _require_positive(lease_seconds, "lease_seconds")
        claim_token = str(uuid4())
        deliveries = self._repository.claim_due_outbox(
            claim_token=claim_token,
            limit=limit,
            lease_seconds=lease_seconds,
            now=_aware(now or datetime.now(UTC), "now"),
        )
        return IngestOutboxClaim(claim_token, deliveries)

    def ack(self, delivery_id: str, claim_token: str) -> bool:
        return self._repository.ack_outbox_delivery(
            _uuid(delivery_id, "delivery_id"),
            claim_token=_require_nonblank(claim_token, "claim_token"),
        )

    def release(
        self,
        delivery_id: str,
        claim_token: str,
        *,
        available_at: datetime,
        error_code: str,
    ) -> bool:
        return self._repository.release_outbox_delivery(
            _uuid(delivery_id, "delivery_id"),
            claim_token=_require_nonblank(claim_token, "claim_token"),
            available_at=_aware(available_at, "available_at"),
            error_code=_require_nonblank(error_code, "error_code"),
        )


def dispatch_pending_deliveries(
    service: IngestDeliveryService,
    queue: IngestQueue,
    *,
    limit: int = 100,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> IngestDeliveryDispatchResult:
    observed_at = _aware(now or datetime.now(UTC), "now")
    claim = service.claim_due(
        limit=limit,
        lease_seconds=lease_seconds,
        now=observed_at,
    )
    published: list[str] = []
    released: list[str] = []
    for delivery in claim.deliveries:
        try:
            queue.enqueue(IngestJobPayload.from_dict(delivery.payload))
        except RuntimeError:
            retry_at = observed_at + timedelta(
                seconds=_retry_delay_seconds(delivery.publish_attempt_count)
            )
            if not service.release(
                delivery.delivery_id,
                claim.claim_token,
                available_at=retry_at,
                error_code="queue_unavailable",
            ):
                raise RuntimeError("ingest outbox release lease was lost")
            released.append(delivery.delivery_id)
            continue
        if not service.ack(delivery.delivery_id, claim.claim_token):
            raise RuntimeError("ingest outbox acknowledgement lease was lost")
        published.append(delivery.delivery_id)
    claimed = tuple(delivery.delivery_id for delivery in claim.deliveries)
    return IngestDeliveryDispatchResult(claimed, tuple(published), tuple(released))


def _pending_delivery(
    message: IngestJobPayload,
    *,
    event_kind: str,
    delivery_id: str | None,
    available_at: datetime | None,
) -> PendingIngestDelivery:
    selected_delivery_id = _uuid(delivery_id or str(uuid4()), "delivery_id")
    wire_message = replace(message, delivery_id=selected_delivery_id)
    return PendingIngestDelivery(
        delivery_id=selected_delivery_id,
        job_id=message.job_id,
        event_kind=_event_kind(event_kind),
        payload=wire_message.to_dict(),
        available_at=_aware(available_at or datetime.now(UTC), "available_at"),
    )


def _require_job_id(message: IngestJobPayload, job_id: str) -> None:
    if message.job_id != job_id:
        raise ValueError("ingest message job_id does not match job")


def _event_kind(value: str) -> str:
    selected = _require_nonblank(value, "event_kind")
    if len(selected) > 100:
        raise ValueError("event_kind must be at most 100 characters")
    return selected


def _uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _require_nonblank(value: str, field: str) -> str:
    selected = value.strip()
    if not selected:
        raise ValueError(f"{field} must not be blank")
    return selected


def _require_positive(value: int, field: str) -> None:
    if isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be positive")


def _retry_delay_seconds(attempt_count: int) -> int:
    return min(300, 5 * (2 ** min(max(attempt_count - 1, 0), 6)))
