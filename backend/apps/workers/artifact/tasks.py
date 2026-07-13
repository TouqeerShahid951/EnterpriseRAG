"""Celery task adapter for durable artifact-generation deliveries."""

from __future__ import annotations

from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded

from rag.artifact_jobs.dependencies import (
    get_artifact_context_validator,
    get_artifact_job_executor,
    get_artifact_job_repository,
)
from rag.artifact_jobs.task_execution import ArtifactDeliveryRetry, run_artifact_job
from rag.core.config import settings

from .celery_app import celery_app


@celery_app.task(
    bind=True,
    name=settings.artifact_task_name,
    max_retries=None,
    shared=False,
    lazy=False,
)
def generate_artifact_job(self: Any, job_id: str) -> dict[str, object]:
    try:
        return run_artifact_job(
            job_id,
            repository=get_artifact_job_repository(),
            executor_factory=get_artifact_job_executor,
            context_validator=get_artifact_context_validator(),
            timeout_error_types=(SoftTimeLimitExceeded,),
        )
    except ArtifactDeliveryRetry as retry:
        raise self.retry(
            exc=retry.cause,
            countdown=retry.countdown,
            max_retries=None,
        )
