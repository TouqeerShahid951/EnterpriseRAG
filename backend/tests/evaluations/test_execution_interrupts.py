"""Regression tests for evaluation worker interruption propagation."""

from __future__ import annotations

from types import SimpleNamespace

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.evaluations.execution import EvaluationRunExecutor
from rag.schemas.evaluations import EvaluationCase


class _Repository:
    def __init__(self, run: object, case: EvaluationCase) -> None:
        self.run = run
        self.case = case

    def start_attempt(self, _run_id: str) -> tuple[object, bool]:
        return self.run, True

    def clear_case_results(self, _run_id: str) -> None:
        return None

    def get_dataset(self, _dataset_id: str) -> object:
        return SimpleNamespace(cases=(self.case,))

    def get_run(self, _run_id: str) -> object:
        return self.run

    def heartbeat(self, _run_id: str) -> object:
        return self.run


class _Documents:
    def list_documents(self, *, state: str) -> list[object]:
        assert state == "active"
        return []


class _InterruptedService:
    def __init__(self) -> None:
        self.ollama = self

    def embed(self, _text: str) -> list[float]:
        raise SoftTimeLimitExceeded()

    def answer_query(self, *_args: object, **_kwargs: object) -> object:
        raise SoftTimeLimitExceeded()


def _run() -> object:
    return SimpleNamespace(
        id="run-1",
        dataset_id="dataset-1",
        selected_case_ids=(),
        user_id="user-1",
        user_email="user@example.com",
        account_type="member",
        group_paths=("/ops",),
        clearance_level="NATO_UNCLASSIFIED",
        permission_version=1,
        group_path=None,
        document_ids=(),
        cancellation_requested=False,
        status="running",
    )


def _executor(repository: _Repository, service: _InterruptedService) -> EvaluationRunExecutor:
    config = SimpleNamespace(
        evaluation_answer_llm_verifier_enabled=False,
        evaluation_diagnostic_top_k=10,
    )
    return EvaluationRunExecutor(
        repo_factory=lambda: repository,  # type: ignore[arg-type]
        document_repo_factory=_Documents,  # type: ignore[arg-type]
        rag_service_factory=lambda: service,  # type: ignore[arg-type]
        config=config,  # type: ignore[arg-type]
        interrupt_error_types=(SoftTimeLimitExceeded,),
    )


def test_query_soft_timeout_reaches_the_delivery_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = EvaluationCase(id="case-1", question="Question?", must_include=["answer"])
    run = _run()
    repository = _Repository(run, case)
    service = _InterruptedService()
    executor = _executor(repository, service)
    monkeypatch.setattr(executor, "_diagnostic", lambda *_args, **_kwargs: {})

    with pytest.raises(SoftTimeLimitExceeded):
        executor.execute("run-1")


def test_diagnostic_soft_timeout_reaches_the_delivery_policy() -> None:
    case = EvaluationCase(id="case-1", question="Question?")
    run = _run()
    repository = _Repository(run, case)
    service = _InterruptedService()
    executor = _executor(repository, service)

    with pytest.raises(SoftTimeLimitExceeded):
        executor._diagnostic(
            case,
            run=run,  # type: ignore[arg-type]
            user=object(),  # type: ignore[arg-type]
            service=service,  # type: ignore[arg-type]
            document_repo=_Documents(),  # type: ignore[arg-type]
        )
