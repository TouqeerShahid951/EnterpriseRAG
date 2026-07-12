"""Celery task entrypoint for durable RAG evaluation runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from billiard.exceptions import SoftTimeLimitExceeded
from celery import shared_task

from .execution import EvaluationRunCancelled, default_evaluation_run_executor
from .repository import get_evaluation_repository


@shared_task(bind=True, name="rag.evaluations.tasks.run_evaluation")
def run_evaluation(self: Any, run_id: str) -> dict[str, object]:
    repo = get_evaluation_repository()
    try:
        result = default_evaluation_run_executor().execute(run_id)
    except EvaluationRunCancelled:
        run = repo.update_run(run_id, {
            "status": "cancelled",
            "stage": "cancelled",
            "progress_pct": 100,
            "completed_at": datetime.now(UTC),
        })
        return {"run_id": run_id, "status": run.status if run else "cancelled"}
    except SoftTimeLimitExceeded as exc:
        return _retry_or_fail(self, run_id, exc, "evaluation_timeout")
    except Exception as exc:
        return _retry_or_fail(self, run_id, exc, "evaluation_run_failed")
    return {"run_id": run_id, "status": result.status}


def _retry_or_fail(task: Any, run_id: str, exc: Exception, code: str) -> dict[str, object]:
    repo = get_evaluation_repository()
    run = repo.get_run(run_id)
    if run is None:
        raise exc
    if run.attempt_count >= run.max_attempts:
        repo.update_run(run_id, {
            "status": "failed",
            "stage": "failed",
            "progress_pct": 100,
            "error_code": code,
            "error_message_safe": str(exc)[:400],
            "completed_at": datetime.now(UTC),
        })
        raise exc
    countdown = 30 * (2 ** max(0, run.attempt_count - 1))
    repo.update_run(run_id, {
        "status": "queued",
        "stage": "queued",
        "progress_pct": 0,
        "error_code": code,
        "error_message_safe": str(exc)[:400],
    })
    raise task.retry(exc=exc, countdown=countdown, max_retries=None)
