"""Regression tests for evaluation worker interruption propagation."""

from __future__ import annotations

from types import SimpleNamespace

from billiard.exceptions import SoftTimeLimitExceeded
import pytest

from rag.auth.context import UserContext
from rag.core.config import Settings
from rag.evaluations.execution import EvaluationCaseExecutor
from rag.evaluations.runtime_pins import RUNTIME_PINS_KEY, capture_runtime_pins
from rag.query.configuration.mapping import rag_config_response
from rag.query.configuration.models import RagConfigRecord
from rag.query.retrieval.retrieval_trace import RetrievalTrace
from rag.query.schemas import RAGResponse
from rag.query.service import QueryExecutionResult
from rag.evaluations.schemas import EvaluationCase


class _Documents:
    def list_documents(self, *, state: str) -> list[object]:
        assert state == "active"
        return []


class _InterruptedService:
    def execute_query(self, *_args: object, **_kwargs: object) -> object:
        raise SoftTimeLimitExceeded()


class _FailedService:
    def execute_query(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("https://provider.internal/secret-payload")


class _SuccessfulService:
    def __init__(self) -> None:
        self.force_flags: list[bool] = []
        self.rag_config = SimpleNamespace(reranker_model="BAAI/bge-reranker-base")

    def execute_query(self, *_args: object, **kwargs: object) -> QueryExecutionResult:
        self.force_flags.append(bool(kwargs["force_faithfulness_check"]))
        return QueryExecutionResult(
            response=RAGResponse(
                trace_id="trace-1",
                answer="Grounded answer.",
                sources=[],
                conflict_flag=False,
                faithfulness_score=1.0,
                faithfulness_status="checked",
                unfounded_claims=[],
                intent="factual_simple",
                session_id="session-1",
                latency_ms=1,
                degraded=False,
            ),
            retrieval_trace=RetrievalTrace(),
        )


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
        rag_config_snapshot=_snapshot(),
    )


def _executor(service: object) -> EvaluationCaseExecutor:
    config = SimpleNamespace(
        evaluation_answer_llm_verifier_enabled=False,
    )
    return EvaluationCaseExecutor(
        document_repo_factory=_Documents,  # type: ignore[arg-type]
        rag_service_factory=lambda _config, _settings: service,  # type: ignore[arg-type]
        config=config,  # type: ignore[arg-type]
        interrupt_error_types=(SoftTimeLimitExceeded,),
    )


def test_query_soft_timeout_reaches_the_delivery_policy() -> None:
    case = EvaluationCase(id="case-1", question="Question?", must_include=["answer"])
    run = _run()
    service = _InterruptedService()
    executor = _executor(service)

    with pytest.raises(SoftTimeLimitExceeded):
        executor.execute_case(run, case)  # type: ignore[arg-type]


def test_ordinary_query_failure_is_a_safe_terminal_case_payload() -> None:
    case = EvaluationCase(id="case-1", question="Question?", must_include=["answer"])
    executor = _executor(_FailedService())  # type: ignore[arg-type]

    payload = executor.execute_case(_run(), case)  # type: ignore[arg-type]

    assert payload.status == "error"
    assert payload.passed is False
    assert payload.primary_failure_stage == "runtime"
    assert (
        payload.error_message_safe
        == "Evaluation query execution failed (RuntimeError)."
    )
    assert "provider.internal" not in payload.error_message_safe


@pytest.mark.parametrize(
    ("must_cite_source", "min_score", "expected_force"),
    [(True, 0.0, True), (False, 0.5, True), (False, 0.0, False)],
)
def test_required_evaluation_checks_force_faithfulness_per_case(
    must_cite_source: bool,
    min_score: float,
    expected_force: bool,
) -> None:
    service = _SuccessfulService()
    executor = _executor(service)
    case = EvaluationCase(
        id="case-1",
        question="Question?",
        must_include=["answer"],
        must_cite_source=must_cite_source,
        min_faithfulness_score=min_score,
    )

    executor.execute_case(_run(), case)  # type: ignore[arg-type]

    assert service.force_flags == [expected_force]


def test_invalid_snapshot_fails_safely_without_constructing_query_service() -> None:
    calls = 0

    def service_factory(
        _config: RagConfigRecord, _settings: object
    ) -> _FailedService:
        nonlocal calls
        calls += 1
        return _FailedService()

    executor = EvaluationCaseExecutor(
        document_repo_factory=_Documents,  # type: ignore[arg-type]
        rag_service_factory=service_factory,  # type: ignore[arg-type]
        config=SimpleNamespace(
            evaluation_answer_llm_verifier_enabled=False
        ),  # type: ignore[arg-type]
    )
    run = _run()
    run.rag_config_snapshot = {}

    payload = executor.execute_case(  # type: ignore[arg-type]
        run,
        EvaluationCase(id="case-1", question="Question?", must_include=["answer"]),
    )

    assert calls == 0
    assert payload.status == "error"
    assert payload.primary_failure_stage == "runtime"
    assert payload.checks_json["runtime"]["code"] == (
        "evaluation_rag_config_snapshot_invalid"
    )
    assert payload.error_message_safe == (
        "Evaluation run RAG configuration snapshot is invalid."
    )


def test_worker_uses_frozen_query_settings() -> None:
    submitted_config = Settings(
        application_image_digest="sha256:image-a",
        evaluation_host_profile="host-a",
        evaluation_answer_llm_verifier_enabled=False,
        rag_top_k=7,
    )
    worker_config = Settings(
        application_image_digest="sha256:image-a",
        evaluation_host_profile="host-a",
        evaluation_answer_llm_verifier_enabled=False,
        rag_top_k=99,
    )
    run = _run()
    run.rag_config_snapshot = _pinned_snapshot(submitted_config)
    received: list[Settings] = []
    service = _SuccessfulService()
    executor = EvaluationCaseExecutor(
        document_repo_factory=_Documents,  # type: ignore[arg-type]
        rag_service_factory=lambda _rag, frozen: received.append(frozen) or service,
        config=worker_config,
    )

    payload = executor.execute_case(
        run,  # type: ignore[arg-type]
        EvaluationCase(id="case-1", question="Question?", must_include=["answer"]),
    )

    assert payload.status == "ok"
    assert received[0].rag_top_k == 7


def test_worker_fails_closed_when_image_pin_drifts() -> None:
    submitted_config = Settings(
        application_image_digest="sha256:image-a",
        evaluation_host_profile="host-a",
        evaluation_answer_llm_verifier_enabled=False,
    )
    run = _run()
    run.rag_config_snapshot = _pinned_snapshot(submitted_config)
    calls = 0

    def service_factory(_rag: RagConfigRecord, _config: Settings) -> _FailedService:
        nonlocal calls
        calls += 1
        return _FailedService()

    executor = EvaluationCaseExecutor(
        document_repo_factory=_Documents,  # type: ignore[arg-type]
        rag_service_factory=service_factory,
        config=submitted_config.model_copy(
            update={"application_image_digest": "sha256:image-b"}
        ),
    )

    payload = executor.execute_case(  # type: ignore[arg-type]
        run,
        EvaluationCase(id="case-1", question="Question?"),
    )

    assert calls == 0
    assert payload.status == "error"
    assert payload.checks_json["runtime"]["code"] == "evaluation_runtime_pin_drift"


def _snapshot() -> dict[str, object]:
    return rag_config_response(
        RagConfigRecord(
            base_url="http://ollama:11434",
            chat_model="qwen3:8b",
            embed_model="nomic-embed-text:latest",
            faithfulness_model="qwen3:8b",
            chat_timeout_seconds=180,
            embed_timeout_seconds=45,
        )
    ).model_dump(mode="json")


def _pinned_snapshot(config: Settings) -> dict[str, object]:
    snapshot = _snapshot()
    snapshot[RUNTIME_PINS_KEY] = capture_runtime_pins(
        config=config,
        rag_config_snapshot=snapshot,
        document_repo=_Documents(),  # type: ignore[arg-type]
        user=UserContext(
            user_id="user-1",
            email="user@example.com",
            account_type="member",
            group_paths=("/ops",),
            clearance_level="NATO_UNCLASSIFIED",
            permission_version=1,
        ),
        group_path=None,
        document_ids=(),
    )
    return snapshot
