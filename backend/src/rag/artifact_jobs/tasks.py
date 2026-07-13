"""Celery task adapter for durable document generation."""

from __future__ import annotations

from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded
from celery import shared_task

from ..core.config import settings
from .dependencies import (
    get_artifact_context_validator,
    get_artifact_job_executor,
    get_artifact_job_repository,
)
from .task_execution import ArtifactDeliveryRetry, run_artifact_job


@shared_task(
    bind=True,
    name=settings.artifact_task_name,
    max_retries=None,
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
