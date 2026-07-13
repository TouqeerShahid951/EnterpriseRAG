"""Evaluation delivery policy tests independent of Celery composition."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from rag.evaluations.execution import EvaluationRunCancelled
from rag.evaluations.task_execution import (
    EvaluationDeliveryRetry,
    run_evaluation_run,
)


@dataclass
class _Run:
    status: str = "running"
    attempt_count: int = 1
    max_attempts: int = 3


class _Repository:
    def __init__(self, run: _Run | None) -> None:
        self.run = run
        self.updates: list[dict[str, Any]] = []

    def get_run(self, _run_id: str) -> _Run | None:
        return self.run

    def update_run(self, _run_id: str, changes: dict[str, Any]) -> _Run | None:
        self.updates.append(changes)
        if self.run is None:
            return None
        for field, value in changes.items():
            if hasattr(self.run, field):
                setattr(self.run, field, value)
        return self.run


class _Executor:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    def execute(self, _run_id: str) -> object:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _execute(repository: _Repository, outcome: object, **kwargs: object) -> dict[str, object]:
    return run_evaluation_run(
        "run-1",
        repository_factory=lambda: repository,  # type: ignore[arg-type]
        executor_factory=lambda: _Executor(outcome),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def test_success_returns_the_executor_status() -> None:
    repository = _Repository(_Run())

    result = _execute(repository, SimpleNamespace(status="complete"))

    assert result == {"run_id": "run-1", "status": "complete"}
    assert repository.updates == []


def test_cancellation_records_a_terminal_result() -> None:
    repository = _Repository(_Run())

    result = _execute(repository, EvaluationRunCancelled())

    assert result == {"run_id": "run-1", "status": "cancelled"}
    assert repository.updates[-1]["status"] == "cancelled"
    assert repository.updates[-1]["stage"] == "cancelled"
    assert repository.updates[-1]["progress_pct"] == 100
    assert repository.updates[-1]["completed_at"] is not None


def test_timeout_requeues_with_exponential_backoff() -> None:
    error = TimeoutError("provider timed out")
    repository = _Repository(_Run(attempt_count=2))

    with pytest.raises(EvaluationDeliveryRetry) as exc_info:
        _execute(repository, error, timeout_error_types=(TimeoutError,))

    assert exc_info.value.cause is error
    assert exc_info.value.countdown == 60
    assert repository.updates == [
        {
            "status": "queued",
            "stage": "queued",
            "progress_pct": 0,
            "error_code": "evaluation_timeout",
            "error_message_safe": "provider timed out",
        }
    ]


def test_generic_failure_uses_the_existing_retry_code_and_delay() -> None:
    error = RuntimeError("backend unavailable")
    repository = _Repository(_Run(attempt_count=1))

    with pytest.raises(EvaluationDeliveryRetry) as exc_info:
        _execute(repository, error)

    assert exc_info.value.cause is error
    assert exc_info.value.countdown == 30
    assert repository.updates[-1]["error_code"] == "evaluation_run_failed"


def test_exhausted_run_is_failed_and_reraises_the_original_error() -> None:
    error = RuntimeError("backend unavailable")
    repository = _Repository(_Run(attempt_count=3, max_attempts=3))

    with pytest.raises(RuntimeError, match="backend unavailable") as exc_info:
        _execute(repository, error)

    assert exc_info.value is error
    assert repository.updates[-1]["status"] == "failed"
    assert repository.updates[-1]["stage"] == "failed"
    assert repository.updates[-1]["progress_pct"] == 100
    assert repository.updates[-1]["error_code"] == "evaluation_run_failed"
    assert repository.updates[-1]["completed_at"] is not None


def test_missing_run_reraises_the_original_error_without_an_update() -> None:
    error = RuntimeError("backend unavailable")
    repository = _Repository(None)

    with pytest.raises(RuntimeError, match="backend unavailable") as exc_info:
        _execute(repository, error)

    assert exc_info.value is error
    assert repository.updates == []
