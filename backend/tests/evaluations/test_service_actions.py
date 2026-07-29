from __future__ import annotations

from dataclasses import replace

import pytest

from rag.auth.context import UserContext
from rag.core.config import Settings
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.evaluations.adapters.memory import InMemoryEvaluationRepository
from rag.evaluations.models import EvaluationCaseResultPayload, EvaluationRunRecord
from rag.evaluations.queue import InMemoryEvaluationRunQueue
from rag.evaluations.runtime_pins import (
    EvaluationRuntimePinError,
    RUNTIME_PINS_KEY,
    _digest,
    capture_runtime_pins,
    resolve_pinned_runtime,
)
from rag.evaluations.service import EvaluationActionError, EvaluationService
from rag.evaluations.schemas import EvaluationCase
from rag.query.configuration.mapping import rag_config_response
from rag.query.configuration.models import RagConfigRecord


def test_service_cancel_fences_owner_and_retry_preserves_completed_case() -> None:
    repository, run = _repository_with_run("case-1", "case-2")
    queue = InMemoryEvaluationRunQueue()
    service = _service(repository, queue)
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

    cancelled = service.cancel(run.id)
    stale = repository.complete_case_attempt(
        run.id,
        second.execution.case_id,
        run_token="worker-b",
        result=_payload("late"),
    )
    retried = service.retry(run.id)

    assert cancelled.status == "cancelled"
    assert stale.accepted is False
    assert retried.status == "queued"
    assert retried.completed_count == 1
    assert queue.run_ids == [run.id]
    assert [item.case_id for item in repository.list_case_results(run.id)] == ["case-1"]


def test_service_rejects_retry_for_quarantined_legacy_run() -> None:
    repository, run = _repository_with_run("case-1")
    repository._case_executions[run.id] = {}  # noqa: SLF001 - legacy-state fixture
    claim = repository.claim_next_case(run.id, run_token="worker-a")
    assert claim.run is not None and claim.run.status == "failed"
    service = _service(repository, InMemoryEvaluationRunQueue())

    with pytest.raises(EvaluationActionError) as exc_info:
        service.retry(run.id)

    assert exc_info.value.code == "evaluation_retry_state_missing"


def test_submit_enqueue_failure_persists_only_generic_safe_message() -> None:
    repository = InMemoryEvaluationRepository()
    case = EvaluationCase(id="case-1", question="Question?", must_include=["answer"])
    dataset = repository.create_dataset(
        name="Queue safety",
        description=None,
        source_format="json",
        cases=[case],
        metadata={},
        created_by=None,
    )

    class FailedQueue:
        def enqueue(self, _run_id: str) -> None:
            raise RuntimeError("redis://user:secret@broker.internal/0")

    service = _service(repository, FailedQueue())

    with pytest.raises(EvaluationActionError) as exc_info:
        service.submit_run(
            dataset_id=dataset.id,
            user=_user(),
            group_path="/quality",
            document_ids=[],
            case_ids=[],
            limit=None,
        )

    assert exc_info.value.code == "evaluation_enqueue_failed"
    failed = repository.list_runs()[0]
    assert failed.error_message_safe == "Evaluation run could not be queued."
    assert "broker.internal" not in failed.error_message_safe


def test_submit_run_captures_runtime_pins_once() -> None:
    repository = InMemoryEvaluationRepository()
    queue = InMemoryEvaluationRunQueue()
    documents = InMemoryDocumentRepository()
    documents.create_document(
        title="Pinned.pdf",
        source_id="pinned.pdf",
        group_path="/quality",
        clearance_level="NATO_RESTRICTED",
        doc_type="manual",
        effective_date=None,
        expiry_date=None,
        description=None,
        pending_supersedes=[],
        content_hash="content-a",
        uploaded_by="user-1",
        file_path="memory://pinned.pdf",
        ingest_status="complete",
    )
    dataset = repository.create_dataset(
        name="Pinned run",
        description=None,
        source_format="json",
        cases=[EvaluationCase(id="case-1", question="Question?")],
        metadata={},
        created_by=None,
    )
    config = Settings(
        application_image_digest="sha256:image-a",
        evaluation_host_profile="m4-10c-16g",
        rag_top_k=17,
    )
    rag_snapshot = rag_config_response(
        RagConfigRecord(
            base_url="http://ollama:11434",
            chat_model="chat-a",
            embed_model="embed-a",
            faithfulness_model="faith-a",
            chat_timeout_seconds=180,
            embed_timeout_seconds=45,
        )
    ).model_dump(mode="json")
    calls = 0

    def pins_factory(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return capture_runtime_pins(
            config=config,
            document_repo=documents,
            **kwargs,  # type: ignore[arg-type]
        )

    service = EvaluationService(
        repo_factory=lambda: repository,
        queue_factory=lambda: queue,
        retention_days=30,
        rag_config_snapshot_factory=lambda: dict(rag_snapshot),
        runtime_pins_factory=pins_factory,
    )
    submitted = service.submit_run(
        dataset_id=dataset.id,
        user=_user(),
        group_path="/quality",
        document_ids=[],
        case_ids=[],
        limit=None,
    )
    pins = service.get_run(submitted.id).rag_config_snapshot[RUNTIME_PINS_KEY]

    documents.create_document(
        title="Later.pdf",
        source_id="later.pdf",
        group_path="/quality",
        clearance_level="NATO_RESTRICTED",
        doc_type="manual",
        effective_date=None,
        expiry_date=None,
        description=None,
        pending_supersedes=[],
        content_hash="content-b",
        uploaded_by="user-1",
        file_path="memory://later.pdf",
        ingest_status="complete",
    )

    assert calls == 1
    assert pins["image_digest"] == "sha256:image-a"
    assert pins["host_profile"] == "m4-10c-16g"
    assert str(pins["active_generation"]).startswith("sha256:")
    assert pins["active_document_count"] == 1
    assert str(pins["active_document_content_hash"]).startswith("sha256:")
    assert pins["query_settings"]["rag_top_k"] == 17
    assert pins["model_identifiers"]["chat"] == "chat-a"
    assert service.get_run(submitted.id).rag_config_snapshot[RUNTIME_PINS_KEY] == pins


def test_runtime_pins_ignore_retired_artifact_pipeline_setting() -> None:
    documents = InMemoryDocumentRepository()
    snapshot: dict[str, object] = {"chat_model": "chat-a"}
    pins = capture_runtime_pins(
        config=Settings(document_repository="memory", rag_top_k=17),
        rag_config_snapshot=snapshot,
        document_repo=documents,
        user=_user(),
        group_path="/quality",
        document_ids=[],
    )
    legacy_query_settings = {
        **pins["query_settings"],
        "artifact_pipeline_version": "v1",
    }
    pins["query_settings"] = legacy_query_settings
    pins["query_settings_hash"] = _digest(legacy_query_settings)
    snapshot[RUNTIME_PINS_KEY] = pins

    _, frozen_config = resolve_pinned_runtime(
        snapshot,
        current_config=Settings(document_repository="memory", rag_top_k=3),
        document_repo=documents,
        user=_user(),
        group_path="/quality",
        document_ids=[],
    )

    assert frozen_config.rag_top_k == 17
    assert not hasattr(frozen_config, "artifact_pipeline_version")


def test_runtime_pins_ignore_retired_faithfulness_threshold() -> None:
    documents = InMemoryDocumentRepository()
    snapshot: dict[str, object] = {"chat_model": "chat-a"}
    pins = capture_runtime_pins(
        config=Settings(document_repository="memory", rag_top_k=17),
        rag_config_snapshot=snapshot,
        document_repo=documents,
        user=_user(),
        group_path="/quality",
        document_ids=[],
    )
    legacy_query_settings = {
        **pins["query_settings"],
        "rag_faithfulness_threshold": 0.8,
    }
    pins["query_settings"] = legacy_query_settings
    pins["query_settings_hash"] = _digest(legacy_query_settings)
    snapshot[RUNTIME_PINS_KEY] = pins

    _, frozen_config = resolve_pinned_runtime(
        snapshot,
        current_config=Settings(document_repository="memory", rag_top_k=3),
        document_repo=documents,
        user=_user(),
        group_path="/quality",
        document_ids=[],
    )

    assert frozen_config.rag_top_k == 17
    assert not hasattr(frozen_config, "rag_faithfulness_threshold")


def test_submit_run_does_not_enqueue_when_runtime_pins_are_unavailable() -> None:
    repository = InMemoryEvaluationRepository()
    queue = InMemoryEvaluationRunQueue()
    dataset = repository.create_dataset(
        name="Pin failure",
        description=None,
        source_format="json",
        cases=[EvaluationCase(id="case-1", question="Question?")],
        metadata={},
        created_by=None,
    )

    def fail_pins(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("secret deployment detail")

    service = EvaluationService(
        repo_factory=lambda: repository,
        queue_factory=lambda: queue,
        retention_days=30,
        rag_config_snapshot_factory=lambda: {},
        runtime_pins_factory=fail_pins,
    )

    with pytest.raises(EvaluationActionError) as exc_info:
        service.submit_run(
            dataset_id=dataset.id,
            user=_user(),
            group_path="/quality",
            document_ids=[],
            case_ids=[],
            limit=None,
        )

    assert exc_info.value.code == "evaluation_runtime_pins_unavailable"
    assert repository.list_runs() == []
    assert queue.run_ids == []


def test_runtime_pins_reject_an_active_generation_change() -> None:
    documents = InMemoryDocumentRepository()
    document = documents.create_document(
        title="Pinned.pdf",
        source_id="pinned-generation.pdf",
        group_path="/quality",
        clearance_level="NATO_RESTRICTED",
        doc_type="manual",
        effective_date=None,
        expiry_date=None,
        description=None,
        pending_supersedes=[],
        content_hash="content-a",
        uploaded_by="user-1",
        file_path="memory://pinned.pdf",
        ingest_status="complete",
    )
    documents._documents[document.id] = replace(  # noqa: SLF001 - focused state setup
        document,
        active_index_generation_id="generation-a",
    )
    config = Settings(document_repository="memory")
    snapshot: dict[str, object] = {"chat_model": "chat-a"}
    snapshot[RUNTIME_PINS_KEY] = capture_runtime_pins(
        config=config,
        rag_config_snapshot=snapshot,
        document_repo=documents,
        user=_user(),
        group_path="/quality",
        document_ids=[],
    )

    documents._documents[document.id] = replace(  # noqa: SLF001 - focused state setup
        documents._documents[document.id],
        active_index_generation_id="generation-b",
    )

    with pytest.raises(EvaluationRuntimePinError) as raised:
        resolve_pinned_runtime(
            snapshot,
            current_config=config,
            document_repo=documents,
            user=_user(),
            group_path="/quality",
            document_ids=[],
        )

    assert raised.value.code == "evaluation_runtime_pin_drift"


def _service(
    repository: InMemoryEvaluationRepository,
    queue: object,
) -> EvaluationService:
    return EvaluationService(
        repo_factory=lambda: repository,
        queue_factory=lambda: queue,  # type: ignore[arg-type]
        retention_days=30,
        rag_config_snapshot_factory=lambda: {},
        runtime_pins_factory=lambda **_kwargs: {},
    )


def _repository_with_run(
    *case_ids: str,
) -> tuple[InMemoryEvaluationRepository, EvaluationRunRecord]:
    repository = InMemoryEvaluationRepository()
    cases = [
        EvaluationCase(
            id=case_id,
            question=f"Question for {case_id}?",
            must_include=["answer"],
        )
        for case_id in case_ids
    ]
    dataset = repository.create_dataset(
        name="Service actions",
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


def _payload(answer: str) -> EvaluationCaseResultPayload:
    return EvaluationCaseResultPayload(
        question="Question?",
        status="ok",
        passed=True,
        primary_failure_stage=None,
        failure_stages=(),
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


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.com",
        account_type="member",
        group_paths=("/quality",),
        clearance_level="NATO_RESTRICTED",
        permission_version=1,
    )
