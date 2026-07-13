from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from rag.ingestion import execution as ingestion_execution
from rag.ingestion.adapters.backend import IngestAttempt
from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.execution import (
    IngestDeliveryRetry,
    _job_is_cancelled,
    _record_event,
    _resume_exhausted_review_attempt,
    _retry_or_fail,
    _start_attempt,
    run_ingest_document,
)


class FakeBackend:
    def __init__(
        self,
        *,
        fail_update: bool = False,
        fail_status: bool = False,
        fail_event: bool = False,
    ) -> None:
        self.fail_update = fail_update
        self.fail_status = fail_status
        self.fail_event = fail_event
        self.events: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []

    def start_attempt(self, **_kwargs: object) -> IngestAttempt:
        return IngestAttempt(
            accepted=True,
            disposition="accepted",
            attempt_count=1,
            max_attempts=3,
            job_status="processing",
        )

    def get_job_status(self, *, job_id: str) -> SimpleNamespace:
        if self.fail_status:
            raise ServiceRequestError("backend", "connection refused")
        return SimpleNamespace(status="processing")

    def update_job(self, **kwargs: object) -> None:
        self.updates.append(kwargs)
        if self.fail_update:
            raise ServiceRequestError("backend", "connection refused")

    def record_event(self, *, job_id: str, event_type: str, payload: dict[str, object]) -> None:
        if self.fail_event:
            raise ServiceRequestError("backend", "connection refused")
        self.events.append({"job_id": job_id, "event_type": event_type, "payload": payload})


def test_retry_uses_base_countdown_when_job_is_requeued() -> None:
    backend = FakeBackend()

    with pytest.raises(IngestDeliveryRetry) as exc_info:
        _retry_or_fail(
            config=SimpleNamespace(ingest_stale_after_seconds=120),
            backend=backend,  # type: ignore[arg-type]
            job=_job(),
            attempt=IngestAttempt(accepted=True, disposition="accepted", attempt_count=1, max_attempts=3, job_status="processing"),
            exc=ServiceRequestError("backend", "connection refused"),
            error_code="backend_unavailable",
        )

    assert exc_info.value.countdown == 30
    assert exc_info.value.max_retries is None
    assert backend.updates[0]["status"] == "queued"
    assert backend.events[0]["payload"] == {
        "error_code": "backend_unavailable",
        "attempt_count": 1,
        "next_attempt": 2,
        "countdown_seconds": 30,
        "status_requeued": True,
    }


def test_retry_waits_for_stale_window_when_backend_requeue_update_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = FakeBackend(fail_update=True)
    caplog.set_level(logging.WARNING, logger="rag.ingestion.execution")

    with pytest.raises(IngestDeliveryRetry) as exc_info:
        _retry_or_fail(
            config=SimpleNamespace(ingest_stale_after_seconds=120),
            backend=backend,  # type: ignore[arg-type]
            job=_job(),
            attempt=IngestAttempt(accepted=True, disposition="accepted", attempt_count=1, max_attempts=3, job_status="processing"),
            exc=ServiceRequestError("backend", "connection refused"),
            error_code="backend_unavailable",
        )

    assert exc_info.value.countdown == 125
    assert exc_info.value.max_retries is None
    assert "ingestion job update failed" in caplog.text
    assert backend.updates[0]["status"] == "queued"
    assert backend.events[0]["payload"] == {
        "error_code": "backend_unavailable",
        "attempt_count": 1,
        "next_attempt": 2,
        "countdown_seconds": 125,
        "status_requeued": False,
    }


def test_review_resume_can_continue_at_retry_limit() -> None:
    backend = FakeBackend()
    resumed = _resume_exhausted_review_attempt(
        backend,  # type: ignore[arg-type]
        _job(image_review_batch_id="batch-1"),
        IngestAttempt(accepted=False, disposition="exhausted", attempt_count=3, max_attempts=3, job_status="queued"),
        "worker-1",
    )

    assert resumed is not None
    assert resumed.accepted is True
    assert resumed.disposition == "review_resume"
    assert resumed.attempt_count == 3
    assert backend.updates[0]["status"] == "processing"
    assert backend.updates[0]["run_token"] == "worker-1"
    assert backend.events[0]["event_type"] == "review_resume_after_retry_limit"


def test_start_attempt_transient_failure_requests_a_bounded_delivery_retry() -> None:
    class UnavailableBackend:
        def start_attempt(self, **_kwargs: object) -> object:
            raise ServiceRequestError("backend", "connection refused")

    with pytest.raises(IngestDeliveryRetry) as exc_info:
        _start_attempt(
            UnavailableBackend(),  # type: ignore[arg-type]
            "job-1",
            "worker-1",
        )

    assert exc_info.value.countdown == 30
    assert exc_info.value.max_retries == 12


def test_injected_timeout_reaches_the_transport_neutral_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WorkerTimeout(RuntimeError):
        pass

    backend = FakeBackend()
    config = SimpleNamespace(
        heartbeat_interval_seconds=3600,
        ingest_stale_after_seconds=120,
    )

    def raise_timeout(*_args: object, **_kwargs: object) -> object:
        raise WorkerTimeout("timed out")

    monkeypatch.setattr(
        ingestion_execution,
        "WorkerConfig",
        SimpleNamespace(from_env=lambda: config),
    )
    monkeypatch.setattr(
        ingestion_execution,
        "build_backend_client",
        lambda _config: backend,
    )
    monkeypatch.setattr(
        ingestion_execution,
        "_build_dependencies",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        ingestion_execution,
        "run_ingest_graph",
        raise_timeout,
    )

    with pytest.raises(IngestDeliveryRetry) as exc_info:
        run_ingest_document(
            _job().to_dict(),
            timeout_error_types=(WorkerTimeout,),
        )

    assert isinstance(exc_info.value.cause, WorkerTimeout)
    assert exc_info.value.countdown == 30
    assert exc_info.value.max_retries is None
    assert backend.updates[-1]["status"] == "queued"
    assert backend.events[-1]["payload"]["error_code"] == "ingest_timeout"


def test_best_effort_event_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="rag.ingestion.execution")

    _record_event(
        FakeBackend(fail_event=True),  # type: ignore[arg-type]
        "job-1",
        "retry",
        {},
    )

    assert "ingestion event recording failed" in caplog.text
    assert "job_id=job-1" in caplog.text


def test_best_effort_cancellation_probe_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="rag.ingestion.execution")

    assert (
        _job_is_cancelled(
            FakeBackend(fail_status=True),  # type: ignore[arg-type]
            "job-1",
        )
        is False
    )

    assert "ingestion cancellation probe failed" in caplog.text
    assert "job_id=job-1" in caplog.text


def _job(*, image_review_batch_id: str | None = None) -> IngestJobPayload:
    return IngestJobPayload(
        job_id="job-1",
        doc_id="doc-1",
        file_path="minio://bucket/doc.pdf",
        group_path="/ops",
        effective_date=None,
        supersedes=[],
        content_type="application/pdf",
        image_review_batch_id=image_review_batch_id,
    )
