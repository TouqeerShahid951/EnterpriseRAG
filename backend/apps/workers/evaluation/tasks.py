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
from rag.shared.contracts.task_names import DEFAULT_EVALUATION_TASK_NAME

from .celery_app import celery_app


def _evaluation_run_executor() -> EvaluationRunExecutor:
    return default_evaluation_run_executor(
        interrupt_error_types=(SoftTimeLimitExceeded,),
    )


def _run_evaluation(self: Any, run_id: str) -> dict[str, object]:
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


def _register_evaluation_task(name: str) -> Any:
    return celery_app.task(
        bind=True,
        name=name,
        max_retries=3,
        shared=False,
        lazy=False,
    )(_run_evaluation)


run_evaluation = _register_evaluation_task(settings.evaluation_task_name)
if settings.evaluation_task_name != DEFAULT_EVALUATION_TASK_NAME:
    _register_evaluation_task(DEFAULT_EVALUATION_TASK_NAME)
