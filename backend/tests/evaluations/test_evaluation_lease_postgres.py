from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from rag.evaluations.adapters.postgres import PostgresEvaluationRepository
from rag.evaluations.models import EvaluationCaseResultPayload
from rag.evaluations.schemas import EvaluationCase


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL evaluation lease coverage",
)
def test_postgres_runtime_pins_round_trip() -> None:
    assert TEST_DATABASE_URL is not None
    repository = PostgresEvaluationRepository(TEST_DATABASE_URL)
    user_id = _insert_user(repository)
    snapshot = {
        "chat_model": "chat-a",
        "_runtime_pins": {
            "image_digest": "sha256:image-a",
            "query_settings_hash": "sha256:settings-a",
        },
    }
    dataset_id, run_id = _create_run(
        repository,
        user_id,
        "case-1",
        rag_config_snapshot=snapshot,
    )

    try:
        assert repository.get_run(run_id).rag_config_snapshot == snapshot  # type: ignore[union-attr]
    finally:
        _delete_run_fixture(repository, user_id, dataset_id)


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL evaluation lease coverage",
)
def test_postgres_case_claim_takeover_and_result_fencing() -> None:
    assert TEST_DATABASE_URL is not None
    repository = PostgresEvaluationRepository(TEST_DATABASE_URL)
    user_id = _insert_user(repository)
    dataset_id, run_id = _create_run(repository, user_id, "case-1", "case-2")

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(
                pool.map(
                    lambda worker: repository.claim_next_case(
                        run_id, run_token=f"worker-{worker}"
                    ),
                    range(8),
                )
            )

        winners = [claim for claim in claims if claim.disposition == "claimed"]
        assert len(winners) == 1
        winner = winners[0]
        assert winner.execution is not None
        assert winner.execution.case_id == "case-1"
        assert winner.execution.attempt_count == 1
        assert all(claim.disposition in {"claimed", "busy"} for claim in claims)
        winning_token = winner.execution.run_token
        assert winning_token is not None

        with repository._connect() as conn:
            conn.execute(
                """
                UPDATE rag_evaluation_case_executions
                SET last_heartbeat_at = NOW() - INTERVAL '5 minutes'
                WHERE run_id = %s AND case_id = %s
                """,
                (run_id, "case-1"),
            )

        takeover = repository.claim_next_case(run_id, run_token="worker-current")
        assert takeover.disposition == "claimed"
        assert takeover.execution is not None
        assert takeover.execution.attempt_count == 2
        assert (
            repository.heartbeat_case(run_id, "case-1", run_token=winning_token) is None
        )
        stale_commit = repository.complete_case_attempt(
            run_id,
            "case-1",
            run_token=winning_token,
            result=_payload("stale"),
        )
        assert stale_commit.accepted is False
        assert repository.list_case_results(run_id) == []

        current_commit = repository.complete_case_attempt(
            run_id,
            "case-1",
            run_token="worker-current",
            result=_payload("current"),
        )
        assert current_commit.accepted is True
        assert current_commit.run is not None
        assert current_commit.run.status == "running"
        assert current_commit.run.completed_count == 1
        assert repository.list_case_results(run_id)[0].answer == "current"

        second = repository.claim_next_case(run_id, run_token="worker-second")
        assert second.disposition == "claimed"
        assert second.execution is not None
        assert second.execution.case_id == "case-2"
        assert second.run is not None and second.run.attempt_count == 1
        final = repository.complete_case_attempt(
            run_id,
            "case-2",
            run_token="worker-second",
            result=_payload("second", passed=False),
        )
        assert final.accepted is True
        assert final.run is not None
        assert final.run.status == "complete"
        assert final.run.completed_count == 2
        assert final.run.passed_count == 1
        assert final.run.failed_count == 1
    finally:
        _delete_run_fixture(repository, user_id, dataset_id)


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL evaluation lease coverage",
)
def test_postgres_active_legacy_run_is_not_backfilled_or_retried() -> None:
    assert TEST_DATABASE_URL is not None
    repository = PostgresEvaluationRepository(TEST_DATABASE_URL)
    user_id = _insert_user(repository)
    dataset_id, run_id = _create_run(repository, user_id, "case-1")

    try:
        repository.add_case_result(
            run_id=run_id,
            case_id="case-1",
            case_index=0,
            question="Question for case-1?",
            status="ok",
            passed=True,
        )
        with repository._connect() as conn:
            conn.execute(
                "DELETE FROM rag_evaluation_case_executions WHERE run_id = %s",
                (run_id,),
            )

        repaired_repository = PostgresEvaluationRepository(TEST_DATABASE_URL)
        assert repaired_repository.list_case_executions(run_id) == []
        claim = repaired_repository.claim_next_case(run_id, run_token="worker-a")

        assert claim.disposition == "terminal"
        assert claim.run is not None
        assert claim.run.status == "partial"
        assert claim.run.error_code == "evaluation_case_execution_state_missing"
        retried, accepted = repaired_repository.reset_run_for_retry(run_id)
        assert accepted is False
        assert retried == claim.run
    finally:
        _delete_run_fixture(repository, user_id, dataset_id)


def _insert_user(repository: PostgresEvaluationRepository) -> str:
    user_id = str(uuid4())
    with repository._connect() as conn:
        conn.execute(
            """
            INSERT INTO users (
                id, email, name, password_hash, is_active, account_type,
                clearance_level, must_change_password
            )
            VALUES (%s, %s, %s, %s, TRUE, 'member', 'NATO_RESTRICTED', FALSE)
            """,
            (
                user_id,
                f"evaluation-{uuid4()}@example.test",
                "Evaluation lease test",
                "not-used",
            ),
        )
    return user_id


def _create_run(
    repository: PostgresEvaluationRepository,
    user_id: str,
    *case_ids: str,
    rag_config_snapshot: dict[str, object] | None = None,
) -> tuple[str, str]:
    cases = [
        EvaluationCase(id=case_id, question=f"Question for {case_id}?")
        for case_id in case_ids
    ]
    dataset = repository.create_dataset(
        name="PostgreSQL lease checks",
        description=None,
        source_format="json",
        cases=cases,
        metadata={},
        created_by=None,
    )
    run = repository.create_run(
        dataset_id=dataset.id,
        user_id=user_id,
        permission_version=1,
        user_email="evaluation@example.test",
        account_type="member",
        group_paths=["/quality"],
        clearance_level="NATO_RESTRICTED",
        group_path="/quality",
        document_ids=[],
        selected_case_ids=list(case_ids),
        rag_config_snapshot=rag_config_snapshot or {},
        case_count=len(case_ids),
        retention_days=30,
    )
    return dataset.id, run.id


def _delete_run_fixture(
    repository: PostgresEvaluationRepository,
    user_id: str,
    dataset_id: str,
) -> None:
    with repository._connect() as conn:
        with conn.transaction():
            conn.execute(
                "DELETE FROM rag_evaluation_datasets WHERE id = %s",
                (dataset_id,),
            )
            conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


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
