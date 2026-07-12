"""Celery task entrypoint for durable document generation."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from math import ceil
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from billiard.exceptions import SoftTimeLimitExceeded

from ..core.config import settings
from ..repositories.artifact_jobs import (
    ACTIVE_ARTIFACT_JOB_STATUSES,
    DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT,
    get_artifact_job_repository,
)
from .celery_app import celery_app
from .execution import (
    ArtifactEvidenceUnavailable,
    ArtifactJobCancelled,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
    default_artifact_job_executor,
)


logger = logging.getLogger("rag.artifact_jobs.tasks")
_TASK_SAFE_ERROR_MESSAGES = {
    "artifact_authorization_changed": "Authorization changed while the document was being generated.",
    "artifact_context_rejected": "The generation context was rejected by the backend.",
    "artifact_generation_failed": "Document generation failed. You can retry the job.",
    "artifact_no_evidence": "No authorized evidence was found for this document generation request.",
    "artifact_timeout": "Document generation timed out. You can retry the job.",
}
_HEARTBEAT_INTERVAL_SECONDS = 20
_HEARTBEAT_FAILURE_RETRY_SECONDS = 5


class ArtifactContextRejected(RuntimeError):
    pass


@celery_app.task(
    bind=True,
    name=settings.artifact_task_name,
    max_retries=None,
)
def generate_artifact_job(self: Any, job_id: str) -> dict[str, object]:
    repo = get_artifact_job_repository()
    run_token = str(uuid4())
    stale_before = datetime.now(UTC) - DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT
    try:
        claimed_job, accepted = repo.start_attempt(
            job_id,
            run_token=run_token,
            stale_before=stale_before,
        )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30, max_retries=None)
    if claimed_job is None:
        raise RuntimeError("artifact job was not found")
    if not accepted:
        if claimed_job.status in ACTIVE_ARTIFACT_JOB_STATUSES:
            countdown = _lease_retry_countdown(claimed_job.last_heartbeat_at)
            conflict = ArtifactJobLeaseLost(
                "artifact job is already owned by an active worker"
            )
            raise self.retry(exc=conflict, countdown=countdown, max_retries=None)
        if (
            claimed_job.status == "queued"
            and claimed_job.attempt_count >= claimed_job.max_attempts
        ):
            failed = repo.update_job(
                job_id,
                {
                    "status": "failed",
                    "stage": "failed",
                    "progress_pct": 100,
                    "stage_progress": None,
                    "error_code": "artifact_attempts_exhausted",
                    "error_message_safe": "Document generation exhausted its retry limit.",
                    "completed_at": datetime.now(UTC),
                },
            )
            return {"job_id": job_id, "status": failed.status if failed else "failed"}
        return {"job_id": job_id, "status": claimed_job.status}
    try:
        with _heartbeat(job_id, run_token):
            _validate_internal_context(job_id)
            result = default_artifact_job_executor().execute(
                job_id, run_token=run_token
            )
    except ArtifactJobCancelled:
        job = repo.transition_job(
            job_id,
            run_token=run_token,
            changes={
                "status": "cancelled",
                "stage": "cancelled",
                "progress_pct": 100,
                "stage_progress": None,
                "completed_at": datetime.now(UTC),
            },
        )
        current = job or repo.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "cancelled"}
    except ArtifactJobLeaseLost:
        current = repo.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "failed"}
    except ArtifactPermissionChanged:
        _append_task_error(
            job_id,
            run_token=run_token,
            stage="authorization",
            code="artifact_authorization_changed",
            exc=None,
        )
        failed = repo.transition_job(
            job_id,
            run_token=run_token,
            changes={
                "status": "failed",
                "stage": "failed",
                "progress_pct": 100,
                "stage_progress": None,
                "error_code": "artifact_authorization_changed",
                "error_message_safe": "Authorization changed while the document was being generated.",
                "completed_at": datetime.now(UTC),
            },
        )
        if failed is None:
            current = repo.get_job(job_id)
            return {"job_id": job_id, "status": current.status if current else "failed"}
        raise
    except ArtifactContextRejected:
        _append_task_error(
            job_id,
            run_token=run_token,
            stage="authorization",
            code="artifact_context_rejected",
            exc=None,
        )
        failed = repo.transition_job(
            job_id,
            run_token=run_token,
            changes={
                "status": "failed",
                "stage": "failed",
                "progress_pct": 100,
                "stage_progress": None,
                "error_code": "artifact_context_rejected",
                "error_message_safe": "The generation context was rejected by the backend.",
                "completed_at": datetime.now(UTC),
            },
        )
        current = failed or repo.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "failed"}
    except ArtifactEvidenceUnavailable as exc:
        _append_task_error(
            job_id,
            run_token=run_token,
            stage="retrieving",
            code="artifact_no_evidence",
            exc=exc,
        )
        repo.transition_job(
            job_id,
            run_token=run_token,
            changes={
                "status": "failed",
                "stage": "failed",
                "progress_pct": 100,
                "stage_progress": None,
                "error_code": "artifact_no_evidence",
                "error_message_safe": exc.safe_message,
                "completed_at": datetime.now(UTC),
            },
        )
        return {"job_id": job_id, "status": "failed"}
    except SoftTimeLimitExceeded as exc:
        return _retry_or_fail(self, job_id, run_token, exc, "artifact_timeout")
    except Exception as exc:
        return _retry_or_fail(
            self, job_id, run_token, exc, "artifact_generation_failed"
        )
    return {"job_id": job_id, "status": result.status}


def _retry_or_fail(
    task: Any,
    job_id: str,
    run_token: str,
    exc: Exception,
    code: str,
) -> dict[str, object]:
    repo = get_artifact_job_repository()
    job = repo.get_job(job_id)
    if job is None:
        raise exc
    if job.run_token != run_token:
        return {"job_id": job_id, "status": job.status}
    logger.warning(
        "artifact job attempt failed job_id=%s stage=%s code=%s error_type=%s",
        job_id,
        job.stage,
        code,
        type(exc).__name__,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    _append_task_error(job_id, run_token=run_token, stage=job.stage, code=code, exc=exc)
    safe_message = _safe_task_error_message(code)
    if job.attempt_count >= job.max_attempts:
        failed = repo.transition_job(
            job_id,
            run_token=run_token,
            changes={
                "status": "failed",
                "stage": "failed",
                "progress_pct": 100,
                "stage_progress": None,
                "error_code": code,
                "error_message_safe": safe_message,
                "completed_at": datetime.now(UTC),
            },
        )
        if failed is None:
            current = repo.get_job(job_id)
            return {"job_id": job_id, "status": current.status if current else "failed"}
        raise exc
    countdown = 30 * (2 ** max(0, job.attempt_count - 1))
    queued = repo.transition_job(
        job_id,
        run_token=run_token,
        changes={
            "status": "queued",
            "stage": "queued",
            "progress_pct": 0,
            "stage_progress": None,
            "error_code": code,
            "error_message_safe": safe_message,
        },
    )
    if queued is None:
        current = repo.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "failed"}
    raise task.retry(exc=exc, countdown=countdown, max_retries=None)


def _append_task_error(
    job_id: str,
    *,
    run_token: str,
    stage: str,
    code: str,
    exc: Exception | None,
) -> None:
    repo = get_artifact_job_repository()
    job = repo.get_job(job_id)
    if job is None or job.run_token != run_token:
        return
    errors = list(job.errors_json)
    errors.append(
        {
            "stage": stage,
            "code": code,
            "message": _safe_task_error_message(code),
        }
    )
    repo.transition_job(
        job_id, run_token=run_token, changes={"errors_json": errors[-50:]}
    )


def _safe_task_error_message(code: str) -> str:
    return _TASK_SAFE_ERROR_MESSAGES.get(
        code,
        "Document generation encountered an error.",
    )


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
                raise ArtifactContextRejected(
                    f"artifact job context rejected with status {response.status}"
                )
    except HTTPError as exc:
        if exc.code in {401, 403, 409}:
            raise ArtifactPermissionChanged(
                f"artifact job context rejected with status {exc.code}"
            ) from exc
        if exc.code in {408, 429} or exc.code >= 500:
            raise RuntimeError(
                f"backend unavailable while validating artifact job context (status {exc.code})"
            ) from exc
        raise ArtifactContextRejected(
            f"artifact job context rejected with status {exc.code}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            "backend unavailable while validating artifact job context"
        ) from exc


@contextmanager
def _heartbeat(job_id: str, run_token: str) -> Iterator[None]:
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.is_set():
            try:
                updated = get_artifact_job_repository().heartbeat(
                    job_id, run_token=run_token
                )
            except Exception:
                logger.warning(
                    "artifact job heartbeat failed job_id=%s", job_id, exc_info=True
                )
                if stopped.wait(_HEARTBEAT_FAILURE_RETRY_SECONDS):
                    return
                continue
            if updated is None or stopped.wait(_HEARTBEAT_INTERVAL_SECONDS):
                return

    thread = threading.Thread(
        target=beat, name=f"artifact-heartbeat-{job_id}", daemon=True
    )
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


def _lease_retry_countdown(last_heartbeat_at: datetime | None) -> int:
    if last_heartbeat_at is None:
        return 1
    lease_expires_at = last_heartbeat_at + DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT
    return max(1, ceil((lease_expires_at - datetime.now(UTC)).total_seconds()))
