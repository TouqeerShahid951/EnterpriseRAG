"""Celery task adapter for durable evaluation deliveries."""

from __future__ import annotations

from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded

from rag.core.config import settings
from rag.evaluations.execution import (
    EvaluationRunExecutor,
    default_evaluation_run_executor,
)
from rag.evaluations.repository import get_evaluation_repository
from rag.evaluations.task_execution import (
    EvaluationDeliveryRetry,
    run_evaluation_run,
)

from .celery_app import celery_app


def _evaluation_run_executor() -> EvaluationRunExecutor:
    return default_evaluation_run_executor(
        interrupt_error_types=(SoftTimeLimitExceeded,),
    )


@celery_app.task(
    bind=True,
    name=settings.evaluation_task_name,
    max_retries=3,
    shared=False,
    lazy=False,
)
def run_evaluation(self: Any, run_id: str) -> dict[str, object]:
    try:
        return run_evaluation_run(
            run_id,
            repository_factory=get_evaluation_repository,
            executor_factory=_evaluation_run_executor,
            timeout_error_types=(SoftTimeLimitExceeded,),
        )
    except EvaluationDeliveryRetry as retry:
        raise self.retry(
            exc=retry.cause,
            countdown=retry.countdown,
            max_retries=None,
        )
