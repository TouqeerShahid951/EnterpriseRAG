import pytest

from rag.evaluations.repository import InMemoryEvaluationRepository
from rag.schemas.evaluations import EvaluationCase


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
