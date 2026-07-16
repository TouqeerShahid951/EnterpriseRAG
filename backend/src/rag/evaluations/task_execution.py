"""Transport-neutral execution policy for evaluation worker deliveries."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from math import ceil
import logging
import threading
from uuid import uuid4

from rag.evaluations.schemas import EvaluationCase
from .execution import EvaluationCaseExecutor
from .models import (
    DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT,
    EvaluationCaseCommit,
    EvaluationCaseExecutionRecord,
    EvaluationCaseResultPayload,
    EvaluationRepository,
    EvaluationRunRecord,
)


logger = logging.getLogger(__name__)
_HEARTBEAT_INTERVAL_SECONDS = 15
_HEARTBEAT_FAILURE_RETRY_SECONDS = 5
_SAFE_TIMEOUT_MESSAGE = "Evaluation case exceeded its execution time limit."
_SAFE_FAILURE_MESSAGE = "Evaluation case could not be executed."


class EvaluationDeliveryRetry(RuntimeError):
    """Request that the queue transport redeliver an evaluation after a delay."""

    def __init__(self, cause: Exception, *, countdown: int) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.countdown = countdown


class EvaluationCaseLeaseBusy(RuntimeError):
    """Another delivery owns the run's active case lease."""


def run_evaluation_run(
    run_id: str,
    *,
    repository_factory: Callable[[], EvaluationRepository],
    executor_factory: Callable[[], EvaluationCaseExecutor],
    timeout_error_types: tuple[type[Exception], ...] = (),
) -> dict[str, object]:
    """Claim and execute at most one durable evaluation case delivery."""

    repository = repository_factory()
    run_token = str(uuid4())
    stale_before = datetime.now(UTC) - DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT
    try:
        claim = repository.claim_next_case(
            run_id,
            run_token=run_token,
            stale_before=stale_before,
        )
    except Exception as exc:
        raise EvaluationDeliveryRetry(exc, countdown=30) from exc

    if claim.disposition == "not_found" or claim.run is None:
        raise RuntimeError("evaluation run was not found")
    if claim.disposition == "terminal":
        return _delivery_result(claim.run)
    if claim.disposition == "busy":
        cause = EvaluationCaseLeaseBusy(
            "evaluation run is already owned by an active case worker"
        )
        raise EvaluationDeliveryRetry(
            cause,
            countdown=_lease_retry_countdown(claim.retry_at),
        )
    if claim.execution is None:
        raise RuntimeError("evaluation case claim did not include execution state")

    execution = claim.execution
    if claim.disposition == "exhausted":
        commit = repository.complete_case_attempt(
            run_id,
            execution.case_id,
            run_token=run_token,
            result=_failure_payload(
                question=_case_question(repository, claim.run, execution.case_id),
                failure_stage="runtime",
                message="Evaluation case exhausted its retry limit.",
            ),
            execution_status="failed",
            error_code="evaluation_case_attempts_exhausted",
            error_message_safe="Evaluation case exhausted its retry limit.",
        )
        return _commit_result(repository, run_id, commit)

    case = _selected_case(repository, claim.run, execution.case_id)
    if case is None:
        commit = repository.complete_case_attempt(
            run_id,
            execution.case_id,
            run_token=run_token,
            result=_failure_payload(
                question="",
                failure_stage="dataset",
                message="Evaluation case was not found in its dataset.",
            ),
            execution_status="failed",
            error_code="evaluation_case_not_found",
            error_message_safe="Evaluation case was not found in its dataset.",
        )
        return _commit_result(repository, run_id, commit)

    try:
        with _heartbeat(repository, run_id, execution.case_id, run_token):
            payload = executor_factory().execute_case(claim.run, case)
    except Exception as exc:
        code = (
            "evaluation_timeout"
            if isinstance(exc, timeout_error_types)
            else "evaluation_case_failed"
        )
        return _retry_or_fail_case(
            repository,
            claim.run,
            execution,
            run_token=run_token,
            case=case,
            exc=exc,
            code=code,
        )

    commit = repository.complete_case_attempt(
        run_id,
        execution.case_id,
        run_token=run_token,
        result=payload,
    )
    return _commit_result(repository, run_id, commit)


def _retry_or_fail_case(
    repository: EvaluationRepository,
    run: EvaluationRunRecord,
    execution: EvaluationCaseExecutionRecord,
    *,
    run_token: str,
    case: EvaluationCase,
    exc: Exception,
    code: str,
) -> dict[str, object]:
    if execution.attempt_count >= execution.max_attempts:
        safe_message = (
            _SAFE_TIMEOUT_MESSAGE
            if code == "evaluation_timeout"
            else _SAFE_FAILURE_MESSAGE
        )
        logger.warning(
            "evaluation case attempts exhausted run_id=%s case_id=%s code=%s error_type=%s",
            run.id,
            execution.case_id,
            code,
            type(exc).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        commit = repository.complete_case_attempt(
            run.id,
            execution.case_id,
            run_token=run_token,
            result=_failure_payload(
                question=case.question,
                failure_stage="runtime",
                message=safe_message,
            ),
            execution_status="failed",
            error_code=code,
            error_message_safe=safe_message,
        )
        return _commit_result(repository, run.id, commit)

    safe_message = (
        _SAFE_TIMEOUT_MESSAGE if code == "evaluation_timeout" else _SAFE_FAILURE_MESSAGE
    )
    logger.warning(
        "evaluation case attempt failed run_id=%s case_id=%s attempt=%s code=%s error_type=%s",
        run.id,
        execution.case_id,
        execution.attempt_count,
        code,
        type(exc).__name__,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    requeued = repository.requeue_case_attempt(
        run.id,
        execution.case_id,
        run_token=run_token,
        error_code=code,
        error_message_safe=safe_message,
    )
    if requeued is None:
        current = repository.get_run(run.id)
        return _delivery_result(current or run)
    countdown = 30 * (2 ** max(0, execution.attempt_count - 1))
    raise EvaluationDeliveryRetry(exc, countdown=countdown)


def _selected_case(
    repository: EvaluationRepository,
    run: EvaluationRunRecord,
    case_id: str,
) -> EvaluationCase | None:
    dataset = repository.get_dataset(run.dataset_id)
    if dataset is None:
        return None
    return next((case for case in dataset.cases if case.id == case_id), None)


def _case_question(
    repository: EvaluationRepository,
    run: EvaluationRunRecord,
    case_id: str,
) -> str:
    case = _selected_case(repository, run, case_id)
    return case.question if case is not None else ""


def _failure_payload(
    *,
    question: str,
    failure_stage: str,
    message: str,
) -> EvaluationCaseResultPayload:
    return EvaluationCaseResultPayload(
        question=question,
        status="error",
        passed=False,
        primary_failure_stage=failure_stage,
        failure_stages=(failure_stage,),
        checks_json={failure_stage: {"passed": False, "error": message}},
        answer="",
        sources_json=(),
        diagnostic_json={"status": "error", "error": message},
        trace_id=None,
        node_timings_json=(),
        faithfulness_score=None,
        faithfulness_status=None,
        unfounded_claims=(),
        degraded=False,
        degraded_reason=None,
        latency_ms=0,
        error_message_safe=message,
    )


def _commit_result(
    repository: EvaluationRepository,
    run_id: str,
    commit: EvaluationCaseCommit,
) -> dict[str, object]:
    run = commit.run or repository.get_run(run_id)
    if run is None:
        raise RuntimeError("evaluation run disappeared after case completion")
    return _delivery_result(
        run, continue_run=commit.accepted and run.status == "running"
    )


def _delivery_result(
    run: EvaluationRunRecord,
    *,
    continue_run: bool = False,
) -> dict[str, object]:
    result: dict[str, object] = {"run_id": run.id, "status": run.status}
    if continue_run:
        result["continue"] = True
    return result


@contextmanager
def _heartbeat(
    repository: EvaluationRepository,
    run_id: str,
    case_id: str,
    run_token: str,
) -> Iterator[None]:
    stopped = threading.Event()

    def beat() -> None:
        while not stopped.is_set():
            try:
                updated = repository.heartbeat_case(
                    run_id,
                    case_id,
                    run_token=run_token,
                )
            except Exception:
                logger.warning(
                    "evaluation case heartbeat failed run_id=%s case_id=%s",
                    run_id,
                    case_id,
                    exc_info=True,
                )
                if stopped.wait(_HEARTBEAT_FAILURE_RETRY_SECONDS):
                    return
                continue
            if updated is None or stopped.wait(_HEARTBEAT_INTERVAL_SECONDS):
                return

    thread = threading.Thread(
        target=beat,
        name=f"evaluation-heartbeat-{run_id}-{case_id}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


def _lease_retry_countdown(retry_at: datetime | None) -> int:
    if retry_at is None:
        return 1
    return max(1, ceil((retry_at - datetime.now(UTC)).total_seconds()))
