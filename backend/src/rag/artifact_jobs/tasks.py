"""Celery task entrypoint for durable document generation."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from billiard.exceptions import SoftTimeLimitExceeded

from ..core.config import settings
from ..repositories.artifact_jobs import get_artifact_job_repository
from .celery_app import celery_app
from .execution import (
    ArtifactEvidenceUnavailable,
    ArtifactJobCancelled,
    ArtifactPermissionChanged,
    default_artifact_job_executor,
)


@celery_app.task(bind=True, name="rag.artifact_jobs.tasks.generate_artifact_job")
def generate_artifact_job(self: Any, job_id: str) -> dict[str, object]:
    _validate_internal_context(job_id)
    repo = get_artifact_job_repository()
    try:
        with _heartbeat(job_id):
            result = default_artifact_job_executor().execute(job_id)
    except ArtifactJobCancelled:
        job = repo.update_job(job_id, {
            "status": "cancelled",
            "stage": "cancelled",
            "progress_pct": 100,
        })
        return {"job_id": job_id, "status": job.status if job else "cancelled"}
    except ArtifactPermissionChanged:
        _append_task_error(job_id, stage="authorization", code="artifact_authorization_changed", exc=None)
        repo.update_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress_pct": 100,
            "error_code": "artifact_authorization_changed",
            "error_message_safe": "Authorization changed while the document was being generated.",
        })
        raise
    except ArtifactEvidenceUnavailable as exc:
        _append_task_error(job_id, stage="retrieving", code="artifact_no_evidence", exc=exc)
        repo.update_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress_pct": 100,
            "error_code": "artifact_no_evidence",
            "error_message_safe": exc.safe_message,
        })
        return {"job_id": job_id, "status": "failed"}
    except SoftTimeLimitExceeded as exc:
        return _retry_or_fail(self, job_id, exc, "artifact_timeout")
    except Exception as exc:
        return _retry_or_fail(self, job_id, exc, "artifact_generation_failed")
    return {"job_id": job_id, "status": result.status}


def _retry_or_fail(task: Any, job_id: str, exc: Exception, code: str) -> dict[str, object]:
    repo = get_artifact_job_repository()
    job = repo.get_job(job_id)
    if job is None:
        raise exc
    _append_task_error(job_id, stage=job.stage, code=code, exc=exc)
    if job.attempt_count >= job.max_attempts:
        repo.update_job(job_id, {
            "status": "failed",
            "stage": "failed",
            "progress_pct": 100,
            "error_code": code,
            "error_message_safe": str(exc)[:400],
        })
        raise exc
    countdown = 30 * (2 ** max(0, job.attempt_count - 1))
    repo.update_job(job_id, {
        "status": "queued",
        "stage": "queued",
        "progress_pct": 0,
        "error_code": code,
        "error_message_safe": str(exc)[:400],
    })
    raise task.retry(exc=exc, countdown=countdown, max_retries=None)


def _append_task_error(job_id: str, *, stage: str, code: str, exc: Exception | None) -> None:
    repo = get_artifact_job_repository()
    job = repo.get_job(job_id)
    if job is None:
        return
    errors = list(job.errors_json)
    errors.append({
        "stage": stage,
        "code": code,
        "message": str(exc)[:500] if exc is not None else code,
    })
    repo.update_job(job_id, {"errors_json": errors[-50:]})


def _validate_internal_context(job_id: str) -> None:
    base_url = getattr(settings, "backend_internal_url", None) or "http://api:8000"
    request = Request(
        f"{base_url.rstrip('/')}/internal/artifact-jobs/{job_id}/context",
        headers={"X-Service-Token": settings.service_token},
        method="GET",
    )
    try:
        with urlopen(request, timeout=settings.rag_http_timeout_seconds) as response:
            if response.status != 200:
                raise RuntimeError("artifact job context validation failed")
    except HTTPError as exc:
        raise ArtifactPermissionChanged(f"artifact job context rejected with status {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("backend unavailable while validating artifact job context") from exc


@contextmanager
def _heartbeat(job_id: str) -> Iterator[None]:
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.wait(20):
            get_artifact_job_repository().heartbeat(job_id)

    thread = threading.Thread(target=beat, name=f"artifact-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)
