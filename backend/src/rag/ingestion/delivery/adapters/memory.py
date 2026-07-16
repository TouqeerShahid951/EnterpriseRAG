"""In-memory adapter for atomic ingestion delivery tests."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from ..models import (
    IngestDeliveryMutation,
    IngestOutboxRecord,
    IngestWorkerDeliveryClaim,
    PendingIngestDelivery,
)


class InMemoryIngestDeliveryRepositoryMixin:
    def create_queued_job_with_delivery(
        self,
        delivery: PendingIngestDelivery,
        *,
        doc_id: str,
        origin: str,
        retry_of_job_id: str | None,
    ) -> IngestDeliveryMutation:
        _validate_delivery(delivery, job_id=delivery.job_id, doc_id=doc_id)
        with self._ingest_lock:
            current = self._jobs.get(delivery.job_id)
            if current is not None:
                existing = _existing_delivery(self, delivery)
                if existing is not None:
                    return IngestDeliveryMutation(current, existing, False)
                raise ValueError("ingestion job already exists")
            if delivery.delivery_id in self._ingest_outbox:
                _existing_delivery(self, delivery)
            created = self.create_ingest_job(
                doc_id=doc_id,
                status="queued",
                progress_pct=0,
                origin=origin,
                retry_of_job_id=retry_of_job_id,
            )
            self._jobs.pop(created.id)
            job = replace(
                created,
                id=delivery.job_id,
                active_delivery_id=delivery.delivery_id,
            )
            self._jobs[job.id] = job
            outbox = _insert_delivery(self, delivery)
            _update_document_status(self, doc_id, "queued")
            return IngestDeliveryMutation(job, outbox, True)

    def queue_existing_job_with_delivery(
        self,
        job_id: str,
        delivery: PendingIngestDelivery,
        *,
        expected_statuses: frozenset[str],
        increment_review_resume: bool,
    ) -> IngestDeliveryMutation:
        _validate_delivery(delivery, job_id=job_id)
        with self._ingest_lock:
            current = self._jobs.get(job_id)
            if current is None:
                return IngestDeliveryMutation(None, None, False)
            _validate_delivery(delivery, job_id=job_id, doc_id=current.doc_id)
            existing = _existing_delivery(self, delivery)
            if existing is not None:
                return IngestDeliveryMutation(current, existing, False)
            if current.status not in expected_statuses:
                return IngestDeliveryMutation(current, None, False)
            now = datetime.now(UTC)
            updated = replace(
                current,
                status="queued",
                progress_pct=0,
                stage_progress=None,
                error_code=None,
                error_message_safe=None,
                run_token=None,
                active_delivery_id=delivery.delivery_id,
                review_resume_count=(
                    current.review_resume_count + int(increment_review_resume)
                ),
                completed_at=None,
                updated_at=now,
            )
            self._jobs[job_id] = updated
            outbox = _insert_delivery(self, delivery, now=now)
            _update_document_status(self, current.doc_id, "queued", now=now)
            return IngestDeliveryMutation(updated, outbox, True)

    def recover_stale_job_with_delivery(
        self,
        job_id: str,
        delivery: PendingIngestDelivery,
        *,
        stale_before: datetime,
        max_failures: int,
    ) -> IngestDeliveryMutation:
        _validate_delivery(delivery, job_id=job_id)
        with self._ingest_lock:
            current = self._jobs.get(job_id)
            if current is None:
                return IngestDeliveryMutation(None, None, False)
            existing = _existing_delivery(self, delivery)
            if existing is not None:
                return IngestDeliveryMutation(
                    current,
                    existing,
                    False,
                    current.failure_attempt_count >= max_failures,
                )
            last_activity = (
                current.last_heartbeat_at or current.updated_at or current.created_at
            )
            if (
                current.status != "processing"
                or current.failure_attempt_count >= max_failures
                or (last_activity is not None and last_activity >= stale_before)
            ):
                return IngestDeliveryMutation(
                    current,
                    None,
                    False,
                    current.failure_attempt_count >= max_failures,
                )
            now = datetime.now(UTC)
            failure_count = current.failure_attempt_count + 1
            exhausted = failure_count >= max_failures
            updated = replace(
                current,
                status="failed" if exhausted else "queued",
                progress_pct=100 if exhausted else 0,
                failure_attempt_count=failure_count,
                last_failure_run_token=current.run_token,
                run_token=None,
                active_delivery_id=None if exhausted else delivery.delivery_id,
                error_code="retry_exhausted" if exhausted else None,
                error_message_safe=(
                    "Ingestion could not complete after the retry limit."
                    if exhausted
                    else None
                ),
                completed_at=now if exhausted else None,
                updated_at=now,
            )
            self._jobs[job_id] = updated
            outbox = None if exhausted else _insert_delivery(self, delivery, now=now)
            _update_document_status(
                self,
                current.doc_id,
                "failed" if exhausted else "queued",
                now=now,
            )
            return IngestDeliveryMutation(updated, outbox, True, exhausted)

    def record_worker_failure_with_delivery(
        self,
        job_id: str,
        *,
        run_token: str,
        max_failures: int,
        error_code: str,
        error_message_safe: str,
        delivery: PendingIngestDelivery | None,
    ) -> IngestDeliveryMutation:
        if delivery is not None:
            _validate_delivery(delivery, job_id=job_id)
        with self._ingest_lock:
            current = self._jobs.get(job_id)
            if current is None:
                return IngestDeliveryMutation(None, None, False)
            if current.last_failure_run_token == run_token:
                existing = (
                    self._ingest_outbox.get(current.active_delivery_id)
                    if current.active_delivery_id
                    else None
                )
                return IngestDeliveryMutation(
                    current,
                    existing,
                    False,
                    current.failure_attempt_count >= max_failures,
                )
            if current.status != "processing" or current.run_token != run_token:
                return IngestDeliveryMutation(current, None, False)
            now = datetime.now(UTC)
            failure_count = current.failure_attempt_count + 1
            retrying = delivery is not None and failure_count < max_failures
            exhausted = failure_count >= max_failures
            updated = replace(
                current,
                status="queued" if retrying else "failed",
                progress_pct=0 if retrying else 100,
                failure_attempt_count=failure_count,
                last_failure_run_token=run_token,
                run_token=None,
                active_delivery_id=(
                    delivery.delivery_id if retrying and delivery is not None else None
                ),
                error_code=None if retrying else error_code,
                error_message_safe=None if retrying else error_message_safe,
                completed_at=None if retrying else now,
                updated_at=now,
            )
            self._jobs[job_id] = updated
            outbox = (
                _insert_delivery(self, delivery, now=now)
                if retrying and delivery is not None
                else None
            )
            _update_document_status(
                self,
                current.doc_id,
                "queued" if retrying else "failed",
                now=now,
            )
            return IngestDeliveryMutation(updated, outbox, True, exhausted)

    def claim_worker_delivery(
        self,
        job_id: str,
        *,
        delivery_id: str,
        run_token: str,
        max_failures: int,
    ) -> IngestWorkerDeliveryClaim:
        with self._ingest_lock:
            current = self._jobs.get(job_id)
            if current is None:
                return IngestWorkerDeliveryClaim(None, False, "missing")
            if current.active_delivery_id != delivery_id:
                return IngestWorkerDeliveryClaim(current, False, "duplicate")
            if current.status == "processing" and current.run_token == run_token:
                return IngestWorkerDeliveryClaim(current, True, "accepted")
            if current.failure_attempt_count >= max_failures:
                return IngestWorkerDeliveryClaim(current, False, "exhausted")
            if current.status == "processing":
                return IngestWorkerDeliveryClaim(current, False, "busy")
            if current.status != "queued":
                return IngestWorkerDeliveryClaim(current, False, "duplicate")
            now = datetime.now(UTC)
            updated = replace(
                current,
                status="processing",
                attempt_count=current.attempt_count + 1,
                last_heartbeat_at=now,
                run_token=run_token,
                error_code=None,
                error_message_safe=None,
                completed_at=None,
                updated_at=now,
            )
            self._jobs[job_id] = updated
            _update_document_status(self, current.doc_id, "processing", now=now)
            return IngestWorkerDeliveryClaim(updated, True, "accepted")

    def claim_due_outbox(
        self,
        *,
        claim_token: str,
        limit: int,
        lease_seconds: int,
        now: datetime,
    ) -> tuple[IngestOutboxRecord, ...]:
        with self._ingest_lock:
            due = sorted(
                (
                    item
                    for item in self._ingest_outbox.values()
                    if item.published_at is None
                    and item.available_at <= now
                    and (
                        item.claim_expires_at is None
                        or item.claim_expires_at <= now
                    )
                ),
                key=lambda item: (
                    item.available_at,
                    item.created_at or item.available_at,
                    item.delivery_id,
                ),
            )[:limit]
            claimed: list[IngestOutboxRecord] = []
            for item in due:
                updated = replace(
                    item,
                    claim_token=claim_token,
                    claim_expires_at=now + timedelta(seconds=lease_seconds),
                    publish_attempt_count=item.publish_attempt_count + 1,
                    updated_at=now,
                )
                self._ingest_outbox[item.delivery_id] = updated
                claimed.append(updated)
            for job_id, count in Counter(item.job_id for item in claimed).items():
                job = self._jobs.get(job_id)
                if job is not None:
                    self._jobs[job_id] = replace(
                        job,
                        delivery_count=job.delivery_count + count,
                        updated_at=now,
                    )
            return tuple(claimed)

    def ack_outbox_delivery(self, delivery_id: str, *, claim_token: str) -> bool:
        with self._ingest_lock:
            current = self._ingest_outbox.get(delivery_id)
            if (
                current is None
                or current.published_at is not None
                or current.claim_token != claim_token
            ):
                return False
            now = datetime.now(UTC)
            self._ingest_outbox[delivery_id] = replace(
                current,
                published_at=now,
                claim_token=None,
                claim_expires_at=None,
                last_error_code=None,
                updated_at=now,
            )
            return True

    def release_outbox_delivery(
        self,
        delivery_id: str,
        *,
        claim_token: str,
        available_at: datetime,
        error_code: str,
    ) -> bool:
        with self._ingest_lock:
            current = self._ingest_outbox.get(delivery_id)
            if (
                current is None
                or current.published_at is not None
                or current.claim_token != claim_token
            ):
                return False
            self._ingest_outbox[delivery_id] = replace(
                current,
                available_at=available_at,
                claim_token=None,
                claim_expires_at=None,
                last_error_code=error_code,
                updated_at=datetime.now(UTC),
            )
            return True


def _validate_delivery(
    delivery: PendingIngestDelivery,
    *,
    job_id: str,
    doc_id: str | None = None,
) -> None:
    if delivery.job_id != job_id or delivery.payload.get("job_id") != job_id:
        raise ValueError("delivery job_id does not match ingestion job")
    if delivery.payload.get("delivery_id") != delivery.delivery_id:
        raise ValueError("delivery payload does not contain its delivery_id")
    if doc_id is not None and delivery.payload.get("doc_id") != doc_id:
        raise ValueError("delivery doc_id does not match ingestion job")


def _existing_delivery(
    repository: InMemoryIngestDeliveryRepositoryMixin,
    delivery: PendingIngestDelivery,
) -> IngestOutboxRecord | None:
    existing = repository._ingest_outbox.get(delivery.delivery_id)
    if existing is None:
        return None
    if (
        existing.job_id != delivery.job_id
        or existing.event_kind != delivery.event_kind
        or existing.payload != delivery.payload
    ):
        raise ValueError("delivery_id is already used by a different delivery")
    return existing


def _insert_delivery(
    repository: InMemoryIngestDeliveryRepositoryMixin,
    delivery: PendingIngestDelivery,
    *,
    now: datetime | None = None,
) -> IngestOutboxRecord:
    if delivery.delivery_id in repository._ingest_outbox:
        raise ValueError("delivery_id already exists")
    created_at = now or datetime.now(UTC)
    record = IngestOutboxRecord(
        delivery_id=delivery.delivery_id,
        job_id=delivery.job_id,
        event_kind=delivery.event_kind,
        payload=dict(delivery.payload),
        available_at=delivery.available_at,
        claim_token=None,
        claim_expires_at=None,
        publish_attempt_count=0,
        published_at=None,
        last_error_code=None,
        created_at=created_at,
        updated_at=created_at,
    )
    repository._ingest_outbox[record.delivery_id] = record
    return record


def _update_document_status(
    repository: InMemoryIngestDeliveryRepositoryMixin,
    doc_id: str,
    status: str,
    *,
    now: datetime | None = None,
) -> None:
    document = repository._documents.get(doc_id)
    if document is not None:
        repository._documents[doc_id] = replace(
            document,
            ingest_status=status,
            updated_at=now or datetime.now(UTC),
        )
