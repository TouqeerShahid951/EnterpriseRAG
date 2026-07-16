"""Evaluation delivery policy tests independent of Celery composition."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from rag.evaluations import task_execution
from rag.evaluations.adapters.memory import InMemoryEvaluationRepository
from rag.evaluations.models import (
    DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT,
    EvaluationCaseResultPayload,
    EvaluationRunRecord,
)
from rag.evaluations.task_execution import (
    EvaluationCaseLeaseBusy,
    EvaluationDeliveryRetry,
    run_evaluation_run,
)
from rag.evaluations.schemas import EvaluationCase


class _Executor:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []

    def execute_case(
        self,
        run: EvaluationRunRecord,
        case: EvaluationCase,
    ) -> EvaluationCaseResultPayload:
        self.calls.append((run.id, case.id))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, EvaluationCaseResultPayload)
        return outcome


def test_evaluation_lease_and_heartbeat_match_production_policy() -> None:
    assert DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT == timedelta(seconds=120)
    assert task_execution._HEARTBEAT_INTERVAL_SECONDS == 15  # noqa: SLF001


def test_two_case_run_continues_without_clearing_completed_result() -> None:
    repository, run = _repository_with_run("case-1", "case-2")
    executor = _Executor(_payload("first"), _payload("second", passed=False))

    first = _execute(repository, executor, run.id)

    assert first == {"run_id": run.id, "status": "running", "continue": True}
    assert [item.case_id for item in repository.list_case_results(run.id)] == ["case-1"]

    second = _execute(repository, executor, run.id)

    assert second == {"run_id": run.id, "status": "complete"}
    assert [item.case_id for item in repository.list_case_results(run.id)] == [
        "case-1",
        "case-2",
    ]
    final = repository.get_run(run.id)
    assert final is not None
    assert final.attempt_count == 1
    assert final.completed_count == 2
    assert final.passed_count == 1
    assert final.failed_count == 1


def test_worker_loss_redelivery_reclaims_stale_case_and_finishes_once() -> None:
    repository, run = _repository_with_run("case-1")
    lost = repository.claim_next_case(run.id, run_token="worker-lost")
    assert lost.execution is not None
    repository._case_executions[run.id]["case-1"] = replace(  # noqa: SLF001
        lost.execution,
        last_heartbeat_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    executor = _Executor(_payload("recovered"))

    result = _execute(repository, executor, run.id)

    assert result == {"run_id": run.id, "status": "complete"}
    executions = repository.list_case_executions(run.id)
    assert executions[0].attempt_count == 2
    assert executions[0].run_token is None
    rows = repository.list_case_results(run.id)
    assert len(rows) == 1
    assert rows[0].answer == "recovered"


def test_fresh_duplicate_retries_at_lease_expiry_without_running_next_case() -> None:
    repository, run = _repository_with_run("case-1", "case-2")
    owner = repository.claim_next_case(run.id, run_token="worker-owner")
    assert owner.execution is not None

    with pytest.raises(EvaluationDeliveryRetry) as exc_info:
        _execute(repository, _Executor(_payload("unused")), run.id)

    assert isinstance(exc_info.value.cause, EvaluationCaseLeaseBusy)
    assert 1 <= exc_info.value.countdown <= 120
    executions = repository.list_case_executions(run.id)
    assert [item.status for item in executions] == ["running", "queued"]
    assert executions[1].attempt_count == 0


def test_interrupt_requeues_owned_case_and_next_delivery_retries_it() -> None:
    repository, run = _repository_with_run("case-1")
    timeout = TimeoutError("provider URL must not be persisted")
    executor = _Executor(timeout, _payload("recovered"))

    with pytest.raises(EvaluationDeliveryRetry) as exc_info:
        _execute(
            repository,
            executor,
            run.id,
            timeout_error_types=(TimeoutError,),
        )

    assert exc_info.value.cause is timeout
    assert exc_info.value.countdown == 30
    execution = repository.list_case_executions(run.id)[0]
    assert execution.status == "queued"
    assert execution.attempt_count == 1
    assert execution.run_token is None
    assert execution.error_message_safe == (
        "Evaluation case exceeded its execution time limit."
    )

    result = _execute(repository, executor, run.id)

    assert result == {"run_id": run.id, "status": "complete"}
    assert repository.list_case_executions(run.id)[0].attempt_count == 2


def test_repeated_executor_interrupts_end_in_safe_failed_case_result() -> None:
    repository, run = _repository_with_run("case-1")
    errors = [RuntimeError(f"secret-{index}") for index in range(3)]
    executor = _Executor(*errors)

    for countdown in (30, 60):
        with pytest.raises(EvaluationDeliveryRetry) as exc_info:
            _execute(repository, executor, run.id)
        assert exc_info.value.countdown == countdown

    result = _execute(repository, executor, run.id)

    assert result == {"run_id": run.id, "status": "failed"}
    execution = repository.list_case_executions(run.id)[0]
    assert execution.status == "failed"
    assert execution.attempt_count == execution.max_attempts == 3
    row = repository.list_case_results(run.id)[0]
    assert row.status == "error"
    assert row.error_message_safe == "Evaluation case could not be executed."
    assert "secret" not in row.error_message_safe


def test_cancelled_run_fences_delivery_without_invoking_executor() -> None:
    repository, run = _repository_with_run("case-1")
    repository.cancel_run(run.id)
    executor = _Executor(_payload("unused"))

    result = _execute(repository, executor, run.id)

    assert result == {"run_id": run.id, "status": "cancelled"}
    assert executor.calls == []


def test_heartbeat_recovers_after_transient_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovered = Event()

    class FlakyRepository:
        calls = 0

        def heartbeat_case(
            self, _run_id: str, _case_id: str, *, run_token: str
        ) -> object:
            assert run_token == "worker-a"
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database temporarily unavailable")
            recovered.set()
            return None

    repository = FlakyRepository()
    monkeypatch.setattr(task_execution, "_HEARTBEAT_FAILURE_RETRY_SECONDS", 0)

    with task_execution._heartbeat(  # noqa: SLF001 - focused heartbeat policy test
        repository,  # type: ignore[arg-type]
        "run-1",
        "case-1",
        "worker-a",
    ):
        assert recovered.wait(timeout=1)

    assert repository.calls == 2


def test_missing_run_raises_without_invoking_executor() -> None:
    repository = InMemoryEvaluationRepository()
    executor = _Executor(_payload("unused"))

    with pytest.raises(RuntimeError, match="evaluation run was not found"):
        _execute(repository, executor, "missing-run")

    assert executor.calls == []


def _execute(
    repository: InMemoryEvaluationRepository,
    executor: _Executor,
    run_id: str,
    **kwargs: object,
) -> dict[str, object]:
    return run_evaluation_run(
        run_id,
        repository_factory=lambda: repository,
        executor_factory=lambda: executor,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _repository_with_run(
    *case_ids: str,
) -> tuple[InMemoryEvaluationRepository, EvaluationRunRecord]:
    repository = InMemoryEvaluationRepository()
    cases = [
        EvaluationCase(id=case_id, question=f"Question for {case_id}?")
        for case_id in case_ids
    ]
    dataset = repository.create_dataset(
        name="Delivery checks",
        description=None,
        source_format="json",
        cases=cases,
        metadata={},
        created_by=None,
    )
    run = repository.create_run(
        dataset_id=dataset.id,
        user_id="user-1",
        permission_version=1,
        user_email="user@example.com",
        account_type="member",
        group_paths=["/quality"],
        clearance_level="NATO_RESTRICTED",
        group_path="/quality",
        document_ids=[],
        selected_case_ids=list(case_ids),
        rag_config_snapshot={},
        case_count=len(case_ids),
        retention_days=30,
    )
    return repository, run


def _payload(answer: str, *, passed: bool = True) -> EvaluationCaseResultPayload:
    return EvaluationCaseResultPayload(
        question="Question?",
        status="ok",
        passed=passed,
        primary_failure_stage=None if passed else "answer_content",
        failure_stages=() if passed else ("answer_content",),
        checks_json={"retrieval": {"passed": True}},
        answer=answer,
        sources_json=(),
        diagnostic_json={},
        trace_id=None,
        node_timings_json=(),
        faithfulness_score=None,
        faithfulness_status="skipped",
        unfounded_claims=(),
        degraded=False,
        degraded_reason=None,
        latency_ms=10,
        error_message_safe=None,
    )
