"""Celery task adapter for durable evaluation deliveries."""

from __future__ import annotations

from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded
from celery.exceptions import Reject

from rag.core.config import settings
from rag.evaluations.execution import (
    EvaluationCaseExecutor,
    default_evaluation_case_executor,
)
from rag.evaluations.repository import get_evaluation_repository
from rag.evaluations.task_execution import (
    EvaluationDeliveryRetry,
    run_evaluation_run,
)
from rag.shared.contracts.task_names import DEFAULT_EVALUATION_TASK_NAME

from .celery_app import celery_app


_PUBLISH_RETRY_POLICY = {
    "max_retries": None,
    "interval_start": 0,
    "interval_step": 1,
    "interval_max": 5,
}


def _evaluation_case_executor() -> EvaluationCaseExecutor:
    return default_evaluation_case_executor(
        interrupt_error_types=(SoftTimeLimitExceeded,),
    )


def _run_evaluation(self: Any, run_id: str) -> dict[str, object]:
    try:
        result = run_evaluation_run(
            run_id,
            repository_factory=get_evaluation_repository,
            executor_factory=_evaluation_case_executor,
            timeout_error_types=(SoftTimeLimitExceeded,),
        )
    except EvaluationDeliveryRetry as retry:
        try:
            raise self.retry(
                exc=retry.cause,
                countdown=retry.countdown,
                max_retries=None,
                retry=True,
                retry_policy=_PUBLISH_RETRY_POLICY,
            )
        except Reject as reject:
            raise Reject(reject.reason, requeue=True) from reject
    if result.pop("continue", False):
        try:
            self.apply_async(
                args=[run_id],
                queue=settings.evaluation_queue_name,
                retry=True,
                retry_policy=_PUBLISH_RETRY_POLICY,
            )
        except Exception as exc:
            raise Reject(exc, requeue=True) from exc
    return result


def _register_evaluation_task(name: str) -> Any:
    return celery_app.task(
        bind=True,
        name=name,
        max_retries=None,
        shared=False,
        lazy=False,
    )(_run_evaluation)


run_evaluation = _register_evaluation_task(settings.evaluation_task_name)
if settings.evaluation_task_name != DEFAULT_EVALUATION_TASK_NAME:
    _register_evaluation_task(DEFAULT_EVALUATION_TASK_NAME)
