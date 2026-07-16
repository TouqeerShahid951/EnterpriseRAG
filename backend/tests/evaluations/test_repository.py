from datetime import UTC, datetime, timedelta

import pytest

from rag.evaluations.models import EvaluationCaseResultPayload
from rag.evaluations.repository import InMemoryEvaluationRepository
from rag.evaluations.schemas import EvaluationCase


def test_in_memory_repository_persists_evaluation_run_results() -> None:
    repository = InMemoryEvaluationRepository()
    evaluation_case = EvaluationCase(id="case-1", question="What is the policy?")
    dataset = repository.create_dataset(
        name="Policy checks",
        description=None,
        source_format="json",
        cases=[evaluation_case],
        metadata={"owner": "quality"},
        created_by=None,
    )

    run = repository.create_run(
        dataset_id=dataset.id,
        user_id="user-1",
        permission_version=1,
        user_email="user@example.com",
        account_type="member",
        group_paths=["/quality"],
        clearance_level="NATO_CONFIDENTIAL",
        group_path="/quality",
        document_ids=["document-1"],
        selected_case_ids=[evaluation_case.id],
        rag_config_snapshot={"top_k": 5},
        case_count=1,
        retention_days=30,
    )
    started, acquired = repository.start_attempt(run.id)
    result = repository.add_case_result(
        run_id=run.id,
        case_id=evaluation_case.id,
        case_index=0,
        question=evaluation_case.question,
        status="ok",
        passed=True,
    )

    assert repository.get_dataset(dataset.id) == dataset
    assert acquired is True
    assert started is not None
    assert started.status == "running"
    assert started.clearance_level == "NATO_CONFIDENTIAL"
    assert repository.list_case_results(run.id) == [result]


def test_in_memory_repository_rejects_unknown_run_fields() -> None:
    repository = InMemoryEvaluationRepository()

    with pytest.raises(ValueError, match="unsupported evaluation run fields"):
        repository.update_run("missing-run", {"unknown": True})


def test_case_execution_claim_is_single_owner_and_stale_takeover_fences_old_token() -> (
    None
):
    repository, run = _repository_with_run("case-1", "case-2")

    first = repository.claim_next_case(run.id, run_token="worker-a")
    duplicate = repository.claim_next_case(run.id, run_token="worker-b")

    assert first.disposition == "claimed"
    assert first.execution is not None
    assert first.execution.case_id == "case-1"
    assert first.execution.attempt_count == 1
    assert first.run is not None and first.run.attempt_count == 1
    assert duplicate.disposition == "busy"
    assert duplicate.execution == first.execution

    takeover = repository.claim_next_case(
        run.id,
        run_token="worker-b",
        stale_before=datetime.now(UTC) + timedelta(seconds=1),
    )

    assert takeover.disposition == "claimed"
    assert takeover.execution is not None
    assert takeover.execution.case_id == "case-1"
    assert takeover.execution.attempt_count == 2
    assert repository.heartbeat_case(run.id, "case-1", run_token="worker-a") is None
    rejected = repository.complete_case_attempt(
        run.id,
        "case-1",
        run_token="worker-a",
        result=_payload("stale"),
    )
    assert rejected.accepted is False
    assert repository.list_case_results(run.id) == []

    committed = repository.complete_case_attempt(
        run.id,
        "case-1",
        run_token="worker-b",
        result=_payload("current"),
    )
    assert committed.accepted is True
    assert committed.run is not None
    assert committed.run.status == "running"
    assert committed.run.completed_count == 1
    assert committed.run.progress_pct == 50

    second = repository.claim_next_case(run.id, run_token="worker-c")
    assert second.disposition == "claimed"
    assert second.execution is not None and second.execution.case_id == "case-2"
    assert second.run is not None and second.run.attempt_count == 1
    final = repository.complete_case_attempt(
        run.id,
        "case-2",
        run_token="worker-c",
        result=_payload("second", passed=False),
    )

    assert final.accepted is True
    assert final.run is not None
    assert final.run.status == "complete"
    assert final.run.completed_count == 2
    assert final.run.passed_count == 1
    assert final.run.failed_count == 1
    assert final.run.summary_json["total"] == 2
    assert final.run.summary_json["pass_rate"] == 0.5


def test_exhausted_case_gets_cleanup_lease_without_exceeding_attempt_limit() -> None:
    repository, run = _repository_with_run("case-1")
    claim = repository.claim_next_case(run.id, run_token="worker-a")
    assert claim.execution is not None

    for token in ("worker-b", "worker-c"):
        claim = repository.claim_next_case(
            run.id,
            run_token=token,
            stale_before=datetime.now(UTC) + timedelta(seconds=1),
        )
        assert claim.disposition == "claimed"

    cleanup = repository.claim_next_case(
        run.id,
        run_token="worker-d",
        stale_before=datetime.now(UTC) + timedelta(seconds=1),
    )

    assert cleanup.disposition == "exhausted"
    assert cleanup.execution is not None
    assert cleanup.execution.attempt_count == cleanup.execution.max_attempts == 3
    assert cleanup.execution.run_token == "worker-d"
    failed = repository.complete_case_attempt(
        run.id,
        "case-1",
        run_token="worker-d",
        result=_payload("", passed=False, status="error"),
        execution_status="failed",
        error_code="evaluation_case_attempts_exhausted",
        error_message_safe="Evaluation case exhausted its retry limit.",
    )

    assert failed.accepted is True
    assert failed.execution is not None and failed.execution.status == "failed"
    assert failed.execution.run_token is None
    assert failed.run is not None and failed.run.status == "failed"
    assert failed.run.progress_pct == 100


def test_cancel_fences_owner_and_retry_preserves_completed_cases() -> None:
    repository, run = _repository_with_run("case-1", "case-2")
    first = repository.claim_next_case(run.id, run_token="worker-a")
    assert first.execution is not None
    repository.complete_case_attempt(
        run.id,
        first.execution.case_id,
        run_token="worker-a",
        result=_payload("first"),
    )
    second = repository.claim_next_case(run.id, run_token="worker-b")
    assert second.execution is not None

    cancelled = repository.cancel_run(run.id)

    assert cancelled is not None and cancelled.status == "cancelled"
    rejected = repository.complete_case_attempt(
        run.id,
        second.execution.case_id,
        run_token="worker-b",
        result=_payload("late"),
    )
    assert rejected.accepted is False
    retried, accepted = repository.reset_run_for_retry(run.id)
    assert accepted is True
    assert retried is not None and retried.status == "queued"
    assert retried.completed_count == 1
    assert [item.case_id for item in repository.list_case_results(run.id)] == ["case-1"]
    executions = repository.list_case_executions(run.id)
    assert [item.status for item in executions] == ["complete", "queued"]
    assert executions[1].attempt_count == 0


@pytest.mark.parametrize("has_result", [False, True])
def test_active_legacy_run_without_case_execution_state_is_quarantined(
    has_result: bool,
) -> None:
    repository, run = _repository_with_run("case-1")
    if has_result:
        repository.add_case_result(
            run_id=run.id,
            case_id="case-1",
            case_index=0,
            question="Question for case-1?",
            status="ok",
            passed=True,
        )
    repository._case_executions[run.id] = {}  # noqa: SLF001 - legacy-state fixture

    claim = repository.claim_next_case(run.id, run_token="worker-a")

    assert claim.disposition == "terminal"
    assert claim.run is not None
    assert claim.run.status == ("partial" if has_result else "failed")
    assert claim.run.error_code == "evaluation_case_execution_state_missing"
    retried, accepted = repository.reset_run_for_retry(run.id)
    assert accepted is False
    assert retried == claim.run


def test_run_creation_rejects_inconsistent_case_selection() -> None:
    repository = InMemoryEvaluationRepository()
    dataset = repository.create_dataset(
        name="Cases",
        description=None,
        source_format="json",
        cases=[EvaluationCase(id="case-1", question="Question?")],
        metadata={},
        created_by=None,
    )

    with pytest.raises(ValueError, match="case_count must match"):
        repository.create_run(
            dataset_id=dataset.id,
            user_id="user-1",
            permission_version=1,
            user_email="user@example.com",
            account_type="member",
            group_paths=["/quality"],
            clearance_level="NATO_RESTRICTED",
            group_path="/quality",
            document_ids=[],
            selected_case_ids=["case-1"],
            rag_config_snapshot={},
            case_count=2,
            retention_days=30,
        )


def _repository_with_run(
    *case_ids: str,
) -> tuple[InMemoryEvaluationRepository, object]:
    repository = InMemoryEvaluationRepository()
    cases = [
        EvaluationCase(id=case_id, question=f"Question for {case_id}?")
        for case_id in case_ids
    ]
    dataset = repository.create_dataset(
        name="Lease checks",
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


def _payload(
    answer: str,
    *,
    passed: bool = True,
    status: str = "ok",
) -> EvaluationCaseResultPayload:
    return EvaluationCaseResultPayload(
        question="Question?",
        status=status,
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
