from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag_ingestion.infrastructure.backend import IngestAttempt
from rag_ingestion.infrastructure.http import ServiceRequestError
from rag_ingestion.messages import IngestJobPayload
from rag_ingestion.service import _retry_or_fail


class RetryScheduled(Exception):
    pass


class FakeTask:
    def __init__(self) -> None:
        self.retry_kwargs: dict[str, object] = {}

    def retry(self, **kwargs: object) -> None:
        self.retry_kwargs = kwargs
        raise RetryScheduled


class FakeBackend:
    def __init__(self, *, fail_update: bool = False) -> None:
        self.fail_update = fail_update
        self.events: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []

    def get_job_status(self, *, job_id: str) -> SimpleNamespace:
        return SimpleNamespace(status="processing")

    def update_job(self, **kwargs: object) -> None:
        self.updates.append(kwargs)
        if self.fail_update:
            raise ServiceRequestError("backend", "connection refused")

    def record_event(self, *, job_id: str, event_type: str, payload: dict[str, object]) -> None:
        self.events.append({"job_id": job_id, "event_type": event_type, "payload": payload})


def test_retry_uses_base_countdown_when_job_is_requeued() -> None:
    task = FakeTask()
    backend = FakeBackend()

    with pytest.raises(RetryScheduled):
        _retry_or_fail(
            task,
            config=SimpleNamespace(ingest_stale_after_seconds=120),
            backend=backend,  # type: ignore[arg-type]
            job=_job(),
            attempt=IngestAttempt(accepted=True, disposition="accepted", attempt_count=1, max_attempts=3, job_status="processing"),
            exc=ServiceRequestError("backend", "connection refused"),
            error_code="backend_unavailable",
        )

    assert task.retry_kwargs["countdown"] == 30
    assert backend.updates[0]["status"] == "queued"
    assert backend.events[0]["payload"] == {
        "error_code": "backend_unavailable",
        "attempt_count": 1,
        "next_attempt": 2,
        "countdown_seconds": 30,
        "status_requeued": True,
    }


def test_retry_waits_for_stale_window_when_backend_requeue_update_fails() -> None:
    task = FakeTask()
    backend = FakeBackend(fail_update=True)

    with pytest.raises(RetryScheduled):
        _retry_or_fail(
            task,
            config=SimpleNamespace(ingest_stale_after_seconds=120),
            backend=backend,  # type: ignore[arg-type]
            job=_job(),
            attempt=IngestAttempt(accepted=True, disposition="accepted", attempt_count=1, max_attempts=3, job_status="processing"),
            exc=ServiceRequestError("backend", "connection refused"),
            error_code="backend_unavailable",
        )

    assert task.retry_kwargs["countdown"] == 125
    assert backend.updates[0]["status"] == "queued"
    assert backend.events[0]["payload"] == {
        "error_code": "backend_unavailable",
        "attempt_count": 1,
        "next_attempt": 2,
        "countdown_seconds": 125,
        "status_requeued": False,
    }


def _job() -> IngestJobPayload:
    return IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="minio://bucket/doc.pdf",
        group_path="/ops",
        effective_date=None,
        supersedes=[],
        content_type="application/pdf",
    )
