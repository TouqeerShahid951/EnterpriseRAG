"""Transport-neutral execution policy for evaluation worker deliveries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .execution import EvaluationRunCancelled, EvaluationRunExecutor
from .models import EvaluationRepository


class EvaluationDeliveryRetry(RuntimeError):
    """Request that the queue transport redeliver an evaluation after a delay."""

    def __init__(self, cause: Exception, *, countdown: int) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.countdown = countdown


def run_evaluation_run(
    run_id: str,
    *,
    repository_factory: Callable[[], EvaluationRepository],
    executor_factory: Callable[[], EvaluationRunExecutor],
    timeout_error_types: tuple[type[Exception], ...] = (),
) -> dict[str, object]:
    """Execute one durable evaluation delivery and apply its retry policy."""

    repository = repository_factory()
    try:
        result = executor_factory().execute(run_id)
    except EvaluationRunCancelled:
        run = repository.update_run(
            run_id,
            {
                "status": "cancelled",
                "stage": "cancelled",
                "progress_pct": 100,
                "completed_at": datetime.now(UTC),
            },
        )
        return {"run_id": run_id, "status": run.status if run else "cancelled"}
    except Exception as exc:
        code = (
            "evaluation_timeout"
            if isinstance(exc, timeout_error_types)
            else "evaluation_run_failed"
        )
        return _retry_or_fail(repository, run_id, exc, code)
    return {"run_id": run_id, "status": result.status}


def _retry_or_fail(
    repository: EvaluationRepository,
    run_id: str,
    exc: Exception,
    code: str,
) -> dict[str, object]:
    run = repository.get_run(run_id)
    if run is None:
        raise exc
    if run.attempt_count >= run.max_attempts:
        repository.update_run(
            run_id,
            {
                "status": "failed",
                "stage": "failed",
                "progress_pct": 100,
                "error_code": code,
                "error_message_safe": str(exc)[:400],
                "completed_at": datetime.now(UTC),
            },
        )
        raise exc
    countdown = 30 * (2 ** max(0, run.attempt_count - 1))
    repository.update_run(
        run_id,
        {
            "status": "queued",
            "stage": "queued",
            "progress_pct": 0,
            "error_code": code,
            "error_message_safe": str(exc)[:400],
        },
    )
    raise EvaluationDeliveryRetry(exc, countdown=countdown)
