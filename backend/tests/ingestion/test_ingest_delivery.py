from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from psycopg.errors import UniqueViolation

from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.adapters.postgres import PostgresDocumentRepository
from rag.ingestion.adapters import backend as backend_adapter
from rag.ingestion.adapters.backend import BackendInternalClient
from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.adapters.job_postgres import PostgresIngestJobRepository
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.delivery import IngestDeliveryService, dispatch_pending_deliveries
from rag.ingestion.delivery.schema import INGEST_DELIVERY_SCHEMA_SQL
from rag.ingestion.internal_schemas import (
    InternalJobAttemptRequest,
    InternalJobFailureRequest,
)
from rag.internal.ingest_status_routes import (
    record_ingest_job_failure,
    start_ingest_job_attempt,
)
from rag.internal.schemas import ServiceTokenContext


NOW = datetime(2026, 1, 1, tzinfo=UTC)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
SERVICE_CONTEXT = ServiceTokenContext(service_name="ingestion-worker")


class RecordingQueue:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.attempts: list[IngestJobPayload] = []

    def enqueue(self, message: IngestJobPayload) -> None:
        self.attempts.append(message)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("queue unavailable")

    def cancel(self, _job_id: str) -> None:
        return None


def test_create_queued_job_also_creates_pending_delivery() -> None:
    repo, document_id = _memory_repo_with_document()
    service = IngestDeliveryService(repo)
    job_id, delivery_id = _ids()

    mutation = service.create_queued_job(
        _message(document_id, job_id, delivery_id),
        origin="upload",
        delivery_id=delivery_id,
        available_at=NOW,
    )

    assert mutation.changed is True
    assert mutation.job is not None
    assert mutation.job.id == job_id
    assert mutation.job.status == "queued"
    assert mutation.job.failure_attempt_count == 0
    assert mutation.delivery is not None
    assert mutation.delivery.delivery_id == delivery_id
    assert mutation.delivery.published_at is None
    assert mutation.delivery.payload["delivery_id"] == delivery_id


def test_queue_outage_keeps_pending_delivery_then_dispatches_it() -> None:
    repo, document_id = _memory_repo_with_document()
    service = IngestDeliveryService(repo)
    job_id, delivery_id = _ids()
    service.create_queued_job(
        _message(document_id, job_id, delivery_id),
        origin="upload",
        delivery_id=delivery_id,
        available_at=NOW,
    )
    queue = RecordingQueue(failures=1)

    failed = dispatch_pending_deliveries(service, queue, now=NOW)

    after_failure = repo.get_ingest_job(job_id)
    assert failed.released_ids == (delivery_id,)
    assert after_failure is not None
    assert after_failure.status == "queued"
    assert after_failure.delivery_count == 1
    assert after_failure.failure_attempt_count == 0

    recovered = dispatch_pending_deliveries(
        service,
        queue,
        now=NOW + timedelta(seconds=6),
    )

    final = repo.get_ingest_job(job_id)
    assert recovered.published_ids == (delivery_id,)
    assert final is not None
    assert final.delivery_count == 2
    assert final.failure_attempt_count == 0
    assert service.claim_due(
        limit=10,
        lease_seconds=60,
        now=NOW + timedelta(minutes=1),
    ).deliveries == ()


def test_crash_after_publish_resends_the_same_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, document_id = _memory_repo_with_document()
    service = IngestDeliveryService(repo)
    job_id, delivery_id = _ids()
    service.create_queued_job(
        _message(document_id, job_id, delivery_id),
        origin="upload",
        delivery_id=delivery_id,
        available_at=NOW,
    )
    queue = RecordingQueue()
    ack = service.ack

    def crash_before_ack(_delivery_id: str, _claim_token: str) -> bool:
        raise RuntimeError("simulated dispatcher crash")

    monkeypatch.setattr(service, "ack", crash_before_ack)
    with pytest.raises(RuntimeError, match="simulated dispatcher crash"):
        dispatch_pending_deliveries(
            service,
            queue,
            lease_seconds=1,
            now=NOW,
        )

    monkeypatch.setattr(service, "ack", ack)
    resent = dispatch_pending_deliveries(
        service,
        queue,
        lease_seconds=1,
        now=NOW + timedelta(seconds=2),
    )

    assert resent.published_ids == (delivery_id,)
    assert [message.delivery_id for message in queue.attempts] == [
        delivery_id,
        delivery_id,
    ]
    job = repo.get_ingest_job(job_id)
    assert job is not None
    assert job.delivery_count == 2
    assert job.failure_attempt_count == 0


def test_delivery_id_rejects_delayed_duplicate_and_failure_is_idempotent() -> None:
    repo, document_id = _memory_repo_with_document()
    service = IngestDeliveryService(repo)
    job_id, first_delivery_id = _ids()
    second_delivery_id = str(uuid4())
    service.create_queued_job(
        _message(document_id, job_id, first_delivery_id),
        origin="upload",
        delivery_id=first_delivery_id,
        available_at=NOW,
    )
    claimed = service.claim_worker_delivery(
        job_id,
        delivery_id=first_delivery_id,
        run_token="worker-1",
        max_failures=3,
    )
    assert claimed.claimed is True

    failure = service.record_worker_failure(
        job_id,
        run_token="worker-1",
        max_failures=3,
        error_code="ingest_timeout",
        error_message_safe="Ingestion timed out.",
        retry_message=_message(document_id, job_id, second_delivery_id),
        delivery_id=second_delivery_id,
        available_at=NOW,
    )
    repeated = service.record_worker_failure(
        job_id,
        run_token="worker-1",
        max_failures=3,
        error_code="ingest_timeout",
        error_message_safe="Ingestion timed out.",
        retry_message=_message(document_id, job_id, second_delivery_id),
        delivery_id=second_delivery_id,
        available_at=NOW,
    )
    delayed_duplicate = service.claim_worker_delivery(
        job_id,
        delivery_id=first_delivery_id,
        run_token="worker-late",
        max_failures=3,
    )

    assert failure.changed is True
    assert failure.job is not None
    assert failure.job.failure_attempt_count == 1
    assert repeated.changed is False
    assert repeated.job is not None
    assert repeated.job.failure_attempt_count == 1
    assert delayed_duplicate.claimed is False
    assert delayed_duplicate.disposition == "duplicate"
    assert delayed_duplicate.job is not None
    assert delayed_duplicate.job.status == "queued"
    assert delayed_duplicate.job.failure_attempt_count == 1
    assert service.claim_worker_delivery(
        job_id,
        delivery_id=second_delivery_id,
        run_token="worker-2",
        max_failures=3,
    ).claimed is True


def test_delayed_legacy_payload_cannot_claim_an_active_delivery() -> None:
    repo, document_id = _memory_repo_with_document()
    service = IngestDeliveryService(repo)
    job_id, delivery_id = _ids()
    service.create_queued_job(
        _message(document_id, job_id, delivery_id),
        origin="upload",
        delivery_id=delivery_id,
        available_at=NOW,
    )

    attempt = asyncio.run(
        start_ingest_job_attempt(
            job_id,
            InternalJobAttemptRequest(run_token="legacy-worker"),
            job_repo=repo,
            service=SERVICE_CONTEXT,
        )
    )

    current = repo.get_ingest_job(job_id)
    assert attempt.status == "duplicate"
    assert attempt.run_token is None
    assert current is not None
    assert current.status == "queued"
    assert current.run_token is None
    assert current.attempt_count == 0


def test_review_resume_does_not_consume_failure_budget() -> None:
    repo, document_id = _memory_repo_with_document()
    job = repo.create_ingest_job(
        doc_id=document_id,
        status="human_review",
        progress_pct=35,
        origin="upload",
    )
    delivery_id = str(uuid4())

    mutation = IngestDeliveryService(repo).queue_existing_job(
        job.id,
        _message(document_id, job.id, delivery_id),
        expected_statuses=frozenset({"human_review"}),
        event_kind="review_resume",
        increment_review_resume=True,
        delivery_id=delivery_id,
        available_at=NOW,
    )

    assert mutation.changed is True
    assert mutation.job is not None
    assert mutation.job.status == "queued"
    assert mutation.job.review_resume_count == 1
    assert mutation.job.failure_attempt_count == 0


def test_queue_existing_rejects_document_mismatch_without_outbox() -> None:
    repo, document_id = _memory_repo_with_document()
    job = repo.create_ingest_job(
        doc_id=document_id,
        status="human_review",
        progress_pct=35,
        origin="upload",
    )
    service = IngestDeliveryService(repo)
    delivery_id = str(uuid4())

    with pytest.raises(ValueError, match="delivery doc_id does not match"):
        service.queue_existing_job(
            job.id,
            _message(str(uuid4()), job.id, delivery_id),
            expected_statuses=frozenset({"human_review"}),
            event_kind="review_resume",
            increment_review_resume=True,
            delivery_id=delivery_id,
            available_at=NOW,
        )

    current = repo.get_ingest_job(job.id)
    assert current is not None
    assert current.status == "human_review"
    assert current.active_delivery_id is None
    assert current.review_resume_count == 0
    assert service.claim_due(limit=10, lease_seconds=60, now=NOW).deliveries == ()


def test_three_distinct_worker_failures_exhaust_the_budget() -> None:
    repo, document_id = _memory_repo_with_document()
    service = IngestDeliveryService(repo)
    job_id, delivery_id = _ids()
    service.create_queued_job(
        _message(document_id, job_id, delivery_id),
        origin="upload",
        delivery_id=delivery_id,
        available_at=NOW,
    )

    for failure_number in range(1, 4):
        run_token = f"worker-{failure_number}"
        claim = service.claim_worker_delivery(
            job_id,
            delivery_id=delivery_id,
            run_token=run_token,
            max_failures=3,
        )
        assert claim.claimed is True
        next_delivery_id = str(uuid4())
        mutation = service.record_worker_failure(
            job_id,
            run_token=run_token,
            max_failures=3,
            error_code="ingest_timeout",
            error_message_safe="Ingestion timed out.",
            retry_message=_message(document_id, job_id, next_delivery_id),
            delivery_id=next_delivery_id,
            available_at=NOW,
        )
        assert mutation.job is not None
        assert mutation.job.failure_attempt_count == failure_number
        if failure_number < 3:
            assert mutation.exhausted is False
            assert mutation.job.status == "queued"
            assert mutation.delivery is not None
            delivery_id = next_delivery_id
        else:
            assert mutation.exhausted is True
            assert mutation.job.status == "failed"
            assert mutation.delivery is None


def test_backend_client_sends_delivery_id_and_token_fenced_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, dict[str, object]]] = []

    def request_json(
        _base_url: str,
        path: str,
        **kwargs: object,
    ) -> dict[str, object]:
        payload = kwargs.get("payload")
        assert isinstance(payload, dict)
        requests.append((path, payload))
        if path.endswith("/attempt"):
            return {
                "status": "accepted",
                "attempt_count": 1,
                "failure_attempt_count": 0,
                "max_attempts": 3,
                "job_status": "processing",
                "run_token": "worker-1",
            }
        return {
            "status": "queued",
            "failure_attempt_count": 1,
            "retry_scheduled": True,
            "changed": True,
        }

    monkeypatch.setattr(backend_adapter, "request_json", request_json)
    client = BackendInternalClient(
        base_url="http://backend.test",
        service_token="service-token",
        timeout_seconds=5,
    )
    delivery_id = str(uuid4())
    retry_message = _message("doc-1", "job-1", delivery_id).to_dict()

    attempt = client.start_attempt(
        job_id="job-1",
        run_token="worker-1",
        delivery_id=delivery_id,
    )
    failure = client.record_failure(
        job_id="job-1",
        error_code="ingest_timeout",
        error_message_safe="Ingestion timed out.",
        retry_message=retry_message,
    )

    assert attempt.failure_attempt_count == 0
    assert failure.retry_scheduled is True
    assert requests[0][1] == {
        "run_token": "worker-1",
        "delivery_id": delivery_id,
    }
    assert requests[1][1] == {
        "run_token": "worker-1",
        "error_code": "ingest_timeout",
        "error_message_safe": "Ingestion timed out.",
        "retry_message": retry_message,
    }


def test_backend_client_retries_old_attempt_api_without_delivery_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []

    def request_json(
        _base_url: str,
        _path: str,
        **kwargs: object,
    ) -> dict[str, object]:
        request_payload = kwargs.get("payload")
        assert isinstance(request_payload, dict)
        requests.append(dict(request_payload))
        if len(requests) == 1:
            raise ServiceRequestError(
                "backend",
                json.dumps(
                    {
                        "detail": [
                            {
                                "type": "extra_forbidden",
                                "loc": ["body", "delivery_id"],
                            }
                        ]
                    }
                ),
                422,
            )
        return {
            "status": "accepted",
            "attempt_count": 1,
            "max_attempts": 3,
            "job_status": "processing",
            "run_token": "worker-1",
        }

    monkeypatch.setattr(backend_adapter, "request_json", request_json)
    client = BackendInternalClient(
        base_url="http://backend.test",
        service_token="service-token",
        timeout_seconds=5,
    )

    attempt = client.start_attempt(
        job_id="job-1",
        run_token="worker-1",
        delivery_id=str(uuid4()),
    )

    assert attempt.accepted is True
    assert requests[0]["run_token"] == requests[1]["run_token"] == "worker-1"
    assert "delivery_id" in requests[0]
    assert requests[1] == {"run_token": "worker-1"}


@pytest.mark.parametrize(
    "message",
    [
        "not json",
        json.dumps(
            {
                "detail": [
                    {
                        "type": "extra_forbidden",
                        "loc": ["body", "run_token"],
                    }
                ]
            }
        ),
        json.dumps(
            {
                "detail": [
                    {
                        "type": "value_error",
                        "loc": ["body", "delivery_id"],
                    }
                ]
            }
        ),
    ],
)
def test_backend_client_does_not_fallback_for_other_attempt_422s(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    calls = 0

    def request_json(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise ServiceRequestError("backend", message, 422)

    monkeypatch.setattr(backend_adapter, "request_json", request_json)
    client = BackendInternalClient(
        base_url="http://backend.test",
        service_token="service-token",
        timeout_seconds=5,
    )

    with pytest.raises(ServiceRequestError):
        client.start_attempt(
            job_id="job-1",
            run_token="worker-1",
            delivery_id=str(uuid4()),
        )

    assert calls == 1


def test_internal_failure_records_retry_with_a_fresh_delivery_id() -> None:
    repo, document_id = _memory_repo_with_document()
    delivery_service = IngestDeliveryService(repo)
    job_id, delivery_id = _ids()
    message = _message(document_id, job_id, delivery_id)
    delivery_service.create_queued_job(
        message,
        origin="upload",
        delivery_id=delivery_id,
        available_at=NOW,
    )
    initial_outbox = delivery_service.claim_due(
        limit=1,
        lease_seconds=60,
        now=datetime.now(UTC),
    )
    assert delivery_service.ack(delivery_id, initial_outbox.claim_token) is True

    attempt = asyncio.run(
        start_ingest_job_attempt(
            job_id,
            InternalJobAttemptRequest(
                run_token="worker-1",
                delivery_id=delivery_id,
            ),
            job_repo=repo,
            service=SERVICE_CONTEXT,
        )
    )
    failure = asyncio.run(
        record_ingest_job_failure(
            job_id,
            InternalJobFailureRequest(
                run_token="worker-1",
                error_code="ingest_timeout",
                error_message_safe="Ingestion timed out.",
                retry_message=message.to_dict(),
            ),
            document_repo=repo,
            job_repo=repo,
            service=SERVICE_CONTEXT,
        )
    )
    retry_claim = delivery_service.claim_due(
        limit=10,
        lease_seconds=60,
        now=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert attempt.status == "accepted"
    assert attempt.failure_attempt_count == 0
    assert failure.status == "queued"
    assert failure.failure_attempt_count == 1
    assert failure.retry_scheduled is True
    assert len(retry_claim.deliveries) == 1
    retry = retry_claim.deliveries[0]
    assert retry.delivery_id != delivery_id
    assert retry.payload["delivery_id"] == retry.delivery_id
    assert retry.payload["job_id"] == job_id
    assert retry.payload["doc_id"] == document_id


def test_internal_failure_rejects_invalid_retry_messages_before_mutation() -> None:
    repo, document_id, job_id, delivery_id = _claimed_memory_delivery()
    valid = _message(document_id, job_id, delivery_id).to_dict()
    invalid_messages = [
        {"job_id": job_id, "doc_id": document_id},
        {**valid, "doc_id": str(uuid4())},
    ]

    for retry_message in invalid_messages:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                record_ingest_job_failure(
                    job_id,
                    InternalJobFailureRequest(
                        run_token="worker-1",
                        error_code="ingest_timeout",
                        error_message_safe="Ingestion timed out.",
                        retry_message=retry_message,
                    ),
                    document_repo=repo,
                    job_repo=repo,
                    service=SERVICE_CONTEXT,
                )
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "invalid_ingest_retry_message"

    current = repo.get_ingest_job(job_id)
    assert current is not None
    assert current.status == "processing"
    assert current.failure_attempt_count == 0


def test_internal_failure_rejects_stale_run_token_without_counting_failure() -> None:
    repo, document_id, job_id, delivery_id = _claimed_memory_delivery()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            record_ingest_job_failure(
                job_id,
                InternalJobFailureRequest(
                    run_token="worker-stale",
                    error_code="ingest_timeout",
                    error_message_safe="Ingestion timed out.",
                    retry_message=_message(
                        document_id,
                        job_id,
                        delivery_id,
                    ).to_dict(),
                ),
                document_repo=repo,
                job_repo=repo,
                service=SERVICE_CONTEXT,
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ingest_job_lease_lost"
    current = repo.get_ingest_job(job_id)
    assert current is not None
    assert current.status == "processing"
    assert current.run_token == "worker-1"
    assert current.failure_attempt_count == 0


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL delivery integration coverage",
)
def test_postgres_create_is_atomic_and_delivery_id_survives_retry() -> None:
    assert TEST_DATABASE_URL is not None
    documents = PostgresDocumentRepository(TEST_DATABASE_URL)
    jobs = PostgresIngestJobRepository(TEST_DATABASE_URL)
    service = IngestDeliveryService(jobs)
    with jobs._connect() as conn:
        conn.execute(INGEST_DELIVERY_SCHEMA_SQL)
    group_path = f"/delivery-{uuid4().hex[:12]}"
    with jobs._connect() as conn:
        conn.execute(
            "INSERT INTO groups (path, name) VALUES (%s, %s)",
            (group_path, "Delivery integration test"),
        )
    document_ids: list[str] = []

    try:
        first_document = _postgres_document(documents, group_path)
        second_document = _postgres_document(documents, group_path)
        document_ids.extend((first_document.id, second_document.id))
        first_job_id, first_delivery_id = _ids()
        created = service.create_queued_job(
            _message(first_document.id, first_job_id, first_delivery_id),
            origin="upload",
            delivery_id=first_delivery_id,
            available_at=NOW,
        )
        assert created.job is not None and created.job.status == "queued"
        assert created.delivery is not None and created.delivery.published_at is None

        duplicate_job_id = str(uuid4())
        with pytest.raises(UniqueViolation):
            service.create_queued_job(
                _message(second_document.id, duplicate_job_id, first_delivery_id),
                origin="upload",
                delivery_id=first_delivery_id,
                available_at=NOW,
            )
        assert jobs.get_ingest_job(duplicate_job_id) is None

        review_job = jobs.create_ingest_job(
            doc_id=second_document.id,
            status="human_review",
            progress_pct=35,
            origin="upload",
        )
        mismatched_delivery_id = str(uuid4())
        with pytest.raises(ValueError, match="delivery doc_id does not match"):
            service.queue_existing_job(
                review_job.id,
                _message(
                    first_document.id,
                    review_job.id,
                    mismatched_delivery_id,
                ),
                expected_statuses=frozenset({"human_review"}),
                event_kind="review_resume",
                increment_review_resume=True,
                delivery_id=mismatched_delivery_id,
                available_at=NOW,
            )
        current_review_job = jobs.get_ingest_job(review_job.id)
        assert current_review_job is not None
        assert current_review_job.status == "human_review"
        assert current_review_job.active_delivery_id is None
        with jobs._connect() as conn:
            outbox_row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM ingest_outbox WHERE delivery_id = %s) AS present",
                (mismatched_delivery_id,),
            ).fetchone()
        assert outbox_row is not None and outbox_row["present"] is False

        assert service.claim_worker_delivery(
            first_job_id,
            delivery_id=first_delivery_id,
            run_token="worker-1",
            max_failures=3,
        ).claimed is True
        retry_delivery_id = str(uuid4())
        service.record_worker_failure(
            first_job_id,
            run_token="worker-1",
            max_failures=3,
            error_code="ingest_timeout",
            error_message_safe="Ingestion timed out.",
            retry_message=_message(
                first_document.id,
                first_job_id,
                retry_delivery_id,
            ),
            delivery_id=retry_delivery_id,
            available_at=NOW,
        )
        duplicate = service.claim_worker_delivery(
            first_job_id,
            delivery_id=first_delivery_id,
            run_token="worker-late",
            max_failures=3,
        )
        assert duplicate.claimed is False
        assert duplicate.disposition == "duplicate"
    finally:
        with jobs._connect() as conn:
            with conn.transaction():
                for document_id in document_ids:
                    conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
                conn.execute("DELETE FROM groups WHERE path = %s", (group_path,))


def _memory_repo_with_document() -> tuple[InMemoryDocumentRepository, str]:
    repo = InMemoryDocumentRepository()
    document = repo.create_document(
        title="Delivery test",
        source_id=f"delivery:{uuid4()}",
        group_path="/engineering",
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=None,
        file_path="memory://delivery.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="queued",
    )
    return repo, document.id


def _postgres_document(
    repo: PostgresDocumentRepository,
    group_path: str,
):
    return repo.create_document(
        title="Delivery integration test",
        source_id=f"delivery-test:{uuid4()}",
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=None,
        file_path="memory://delivery-test.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="queued",
    )


def _message(
    document_id: str,
    job_id: str,
    delivery_id: str,
) -> IngestJobPayload:
    return IngestJobPayload(
        job_id=job_id,
        doc_id=document_id,
        file_path="memory://delivery.pdf",
        group_path="/engineering",
        effective_date=None,
        supersedes=[],
        delivery_id=delivery_id,
    )


def _claimed_memory_delivery(
) -> tuple[InMemoryDocumentRepository, str, str, str]:
    repo, document_id = _memory_repo_with_document()
    job_id, delivery_id = _ids()
    IngestDeliveryService(repo).create_queued_job(
        _message(document_id, job_id, delivery_id),
        origin="upload",
        delivery_id=delivery_id,
        available_at=NOW,
    )
    claim = IngestDeliveryService(repo).claim_worker_delivery(
        job_id,
        delivery_id=delivery_id,
        run_token="worker-1",
        max_failures=3,
    )
    assert claim.claimed is True
    return repo, document_id, job_id, delivery_id


def _ids() -> tuple[str, str]:
    return str(uuid4()), str(uuid4())
