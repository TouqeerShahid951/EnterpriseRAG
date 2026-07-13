"""Transport-neutral execution policy for artifact worker deliveries."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
import logging
from math import ceil
import threading
from typing import Iterator, Protocol
from uuid import uuid4

from .execution import (
    ArtifactEvidenceUnavailable,
    ArtifactJobCancelled,
    ArtifactJobExecutor,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)
from .job_models import (
    ACTIVE_ARTIFACT_JOB_STATUSES,
    DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT,
    ArtifactJobRepository,
)


logger = logging.getLogger("rag.artifact_jobs.task_execution")
_TASK_SAFE_ERROR_MESSAGES = {
    "artifact_authorization_changed": "Authorization changed while the document was being generated.",
    "artifact_context_rejected": "The generation context was rejected by the backend.",
    "artifact_generation_failed": "Document generation failed. You can retry the job.",
    "artifact_no_evidence": "No authorized evidence was found for this document generation request.",
    "artifact_timeout": "Document generation timed out. You can retry the job.",
}
_HEARTBEAT_INTERVAL_SECONDS = 20
_HEARTBEAT_FAILURE_RETRY_SECONDS = 5


class ArtifactContextValidator(Protocol):
    """Verify that a claimed job still has an authorized execution context."""

    def validate(self, job_id: str) -> None: ...


class ArtifactContextRejected(RuntimeError):
    """The backend rejected a job context for a non-retryable reason."""


class ArtifactDeliveryRetry(RuntimeError):
    """Request that the queue transport redeliver a job after a delay."""

    def __init__(self, cause: Exception, *, countdown: int) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.countdown = countdown


def run_artifact_job(
    job_id: str,
    *,
    repository: ArtifactJobRepository,
    executor_factory: Callable[[], ArtifactJobExecutor],
    context_validator: ArtifactContextValidator,
    timeout_error_types: tuple[type[Exception], ...] = (),
) -> dict[str, object]:
    """Claim and execute one durable artifact job delivery."""

    run_token = str(uuid4())
    stale_before = datetime.now(UTC) - DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT
    try:
        claimed_job, accepted = repository.start_attempt(
            job_id,
            run_token=run_token,
            stale_before=stale_before,
        )
    except Exception as exc:
        raise ArtifactDeliveryRetry(exc, countdown=30) from exc
    if claimed_job is None:
        raise RuntimeError("artifact job was not found")
    if not accepted:
        if claimed_job.status in ACTIVE_ARTIFACT_JOB_STATUSES:
            conflict = ArtifactJobLeaseLost(
                "artifact job is already owned by an active worker"
            )
            raise ArtifactDeliveryRetry(
                conflict,
                countdown=_lease_retry_countdown(claimed_job.last_heartbeat_at),
            )
        if (
            claimed_job.status == "queued"
            and claimed_job.attempt_count >= claimed_job.max_attempts
        ):
            failed = repository.update_job(
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
        with _heartbeat(repository, job_id, run_token):
            context_validator.validate(job_id)
            result = executor_factory().execute(job_id, run_token=run_token)
    except ArtifactJobCancelled:
        job = repository.transition_job(
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
        current = job or repository.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "cancelled"}
    except ArtifactJobLeaseLost:
        current = repository.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "failed"}
    except ArtifactPermissionChanged:
        _append_task_error(
            repository,
            job_id,
            run_token=run_token,
            stage="authorization",
            code="artifact_authorization_changed",
        )
        failed = repository.transition_job(
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
            current = repository.get_job(job_id)
            return {"job_id": job_id, "status": current.status if current else "failed"}
        raise
    except ArtifactContextRejected:
        _append_task_error(
            repository,
            job_id,
            run_token=run_token,
            stage="authorization",
            code="artifact_context_rejected",
        )
        failed = repository.transition_job(
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
        current = failed or repository.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "failed"}
    except ArtifactEvidenceUnavailable as exc:
        _append_task_error(
            repository,
            job_id,
            run_token=run_token,
            stage="retrieving",
            code="artifact_no_evidence",
        )
        repository.transition_job(
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
    except Exception as exc:
        code = (
            "artifact_timeout"
            if isinstance(exc, timeout_error_types)
            else "artifact_generation_failed"
        )
        return _retry_or_fail(repository, job_id, run_token, exc, code)
    return {"job_id": job_id, "status": result.status}


def _retry_or_fail(
    repository: ArtifactJobRepository,
    job_id: str,
    run_token: str,
    exc: Exception,
    code: str,
) -> dict[str, object]:
    job = repository.get_job(job_id)
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
    _append_task_error(
        repository,
        job_id,
        run_token=run_token,
        stage=job.stage,
        code=code,
    )
    safe_message = _safe_task_error_message(code)
    if job.attempt_count >= job.max_attempts:
        failed = repository.transition_job(
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
            current = repository.get_job(job_id)
            return {"job_id": job_id, "status": current.status if current else "failed"}
        raise exc
    countdown = 30 * (2 ** max(0, job.attempt_count - 1))
    queued = repository.transition_job(
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
        current = repository.get_job(job_id)
        return {"job_id": job_id, "status": current.status if current else "failed"}
    raise ArtifactDeliveryRetry(exc, countdown=countdown)


def _append_task_error(
    repository: ArtifactJobRepository,
    job_id: str,
    *,
    run_token: str,
    stage: str,
    code: str,
) -> None:
    job = repository.get_job(job_id)
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
    repository.transition_job(
        job_id, run_token=run_token, changes={"errors_json": errors[-50:]}
    )


def _safe_task_error_message(code: str) -> str:
    return _TASK_SAFE_ERROR_MESSAGES.get(
        code,
        "Document generation encountered an error.",
    )


@contextmanager
def _heartbeat(
    repository: ArtifactJobRepository,
    job_id: str,
    run_token: str,
) -> Iterator[None]:
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.is_set():
            try:
                updated = repository.heartbeat(job_id, run_token=run_token)
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
