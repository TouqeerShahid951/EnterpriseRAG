from __future__ import annotations

import json

from rag.auth.context import UserContext
from rag.core.config import Settings
from rag.artifact_jobs.schemas import ArtifactJobSummary
from rag.artifact_jobs.submission import ArtifactJobSubmission
from rag.query.schemas import QueryRequest
from rag.query.service import LocalRagService
from rag.query.adapters.chat_history_memory import InMemoryChatHistoryRepository


def test_streamed_artifact_request_enqueues_full_job_without_seeded_answer() -> None:
    artifact_jobs = _ArtifactJobService()
    history = InMemoryChatHistoryRepository()
    service = LocalRagService(
        config=Settings(document_repository="memory"),
        ollama=object(),
        qdrant=object(),
        chat_history_repo=history,
        conflict_checker=object(),
        artifact_job_service=artifact_jobs,
    )

    events = list(service.stream_query(
        QueryRequest(
            query="Create a detailed presentation of all crimes in the FIRs",
            client_request_id="client-request-1",
            group_path="/investigations",
            document_ids=["fir-2", "fir-1"],
        ),
        _user(),
    ))

    assert [event.event for event in events] == ["trace", "artifact_job", "token", "done"]
    assert artifact_jobs.calls[0]["formats"] == ("pptx",)
    assert artifact_jobs.calls[0]["conversation_context"] == []
    assert "seeded_bundle" not in artifact_jobs.calls[0]
    submission = artifact_jobs.calls[0]["submission"]
    assert isinstance(submission, ArtifactJobSubmission)
    assert submission == ArtifactJobSubmission(
        original_request="Create a detailed presentation of all crimes in the FIRs",
        client_request_id="client-request-1",
        group_path="/investigations",
        document_ids=("fir-2", "fir-1"),
    )
    saved = history.get_session(
        session_id=events[-1].data["session_id"],
        user_id="user-1",
        permission_version=1,
    )
    assert saved is not None
    assert len(saved.turns) == 2


def test_direct_artifact_request_ignores_unrelated_history() -> None:
    artifact_jobs = _ArtifactJobService()
    history = InMemoryChatHistoryRepository()
    _save_exchange(history, query="What is the leave policy?")
    service = _service(
        artifact_jobs=artifact_jobs,
        history=history,
        ollama=_UnexpectedResolver(),
    )

    response = service.answer_query(
        QueryRequest(
            query="Create a PDF report about quarterly risk",
            session_id="session-1",
        ),
        _user(),
    )

    assert response.artifact_job is not None
    assert artifact_jobs.calls[0]["conversation_context"] == []


def test_contextual_artifact_without_history_asks_before_queueing() -> None:
    artifact_jobs = _ArtifactJobService()
    service = _service(
        artifact_jobs=artifact_jobs,
        history=InMemoryChatHistoryRepository(),
        ollama=_UnexpectedResolver(),
    )

    response = service.answer_query(
        QueryRequest(query="Export this as PDF", session_id="session-1"),
        _user(),
    )

    assert response.answer_status == "clarification"
    assert response.artifact_job is None
    assert artifact_jobs.calls == []


def test_streamed_artifact_clarification_does_not_emit_an_empty_job_event() -> None:
    artifact_jobs = _ArtifactJobService()
    service = _service(
        artifact_jobs=artifact_jobs,
        history=InMemoryChatHistoryRepository(),
        ollama=_UnexpectedResolver(),
    )

    events = list(
        service.stream_query(
            QueryRequest(query="Turn that into a PDF", session_id="session-1"),
            _user(),
        )
    )

    assert [event.event for event in events] == ["trace", "token", "done"]
    assert events[-1].data["answer_status"] == "clarification"
    assert artifact_jobs.calls == []


def test_previous_answer_reference_reuses_the_previous_query_without_a_model_call() -> None:
    artifact_jobs = _ArtifactJobService()
    history = InMemoryChatHistoryRepository()
    _save_exchange(history, query="What are the quarterly risks?")
    service = _service(
        artifact_jobs=artifact_jobs,
        history=history,
        ollama=_UnexpectedResolver(),
    )

    response = service.answer_query(
        QueryRequest(
            query="Give me the current answer as a Word document",
            session_id="session-1",
        ),
        _user(),
    )

    assert response.artifact_job is not None
    submission = artifact_jobs.calls[0]["submission"]
    assert isinstance(submission, ArtifactJobSubmission)
    assert submission.original_request == "Give me the current answer as a Word document"
    assert artifact_jobs.calls[0]["conversation_context"] == [
        {
            "resolved_query": "What are the quarterly risks?",
            "antecedent_turn_ids": ["previous-user"],
        }
    ]


def test_grounded_previous_answer_uses_existing_seeded_render_path() -> None:
    artifact_jobs = _ArtifactJobService()
    history = InMemoryChatHistoryRepository()
    _save_exchange(
        history,
        query="What are the quarterly risks?",
        sources=[_source()],
    )
    service = _service(
        artifact_jobs=artifact_jobs,
        history=history,
        ollama=_UnexpectedResolver(),
    )

    response = service.answer_query(
        QueryRequest(
            query="Give me the current answer as a Word document",
            session_id="session-1",
        ),
        _user(),
    )

    assert response.artifact_job is not None
    call = artifact_jobs.calls[0]
    assert call["conversation_context"] == []
    assert call["seeded_bundle"].content.sections[0].blocks[0].text == (
        "Quarterly risk is elevated."
    )
    submission = call["submission"]
    assert isinstance(submission, ArtifactJobSubmission)
    assert submission.document_ids == ("doc-1",)


def test_ambiguous_pronoun_uses_existing_context_resolver_before_queueing() -> None:
    artifact_jobs = _ArtifactJobService()
    history = InMemoryChatHistoryRepository()
    _save_exchange(history, query="What are the quarterly risks?")
    resolver = _Resolver()
    service = _service(
        artifact_jobs=artifact_jobs,
        history=history,
        ollama=resolver,
    )

    response = service.answer_query(
        QueryRequest(query="Make that a PDF", session_id="session-1"),
        _user(),
    )

    assert response.artifact_job is not None
    assert resolver.calls == 1
    submission = artifact_jobs.calls[0]["submission"]
    assert isinstance(submission, ArtifactJobSubmission)
    assert submission.original_request == "Make that a PDF"
    assert artifact_jobs.calls[0]["conversation_context"] == [
        {
            "resolved_query": "create a pdf report about quarterly risk",
            "antecedent_turn_ids": ["previous-user"],
        }
    ]


def test_database_scoped_artifact_request_fails_explicitly_instead_of_using_corpus() -> None:
    artifact_jobs = _ArtifactJobService()
    service = _service(
        artifact_jobs=artifact_jobs,
        history=InMemoryChatHistoryRepository(),
        ollama=_UnexpectedResolver(),
    )

    response = service.answer_query(
        QueryRequest(
            query="Create a PDF report about quarterly risk",
            session_id="session-1",
            source_mode="db_only",
            query_source_id="catalog:finance",
        ),
        _user(),
    )

    assert response.answer_status == "clarification"
    assert "document corpus" in response.answer
    assert artifact_jobs.calls == []


def test_non_stream_artifact_request_records_query_lifecycle(monkeypatch) -> None:
    artifact_jobs = _ArtifactJobService()
    history = InMemoryChatHistoryRepository()
    lifecycle_events: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "rag.query.service.log_query_start",
        lambda _ctx, *, stream: lifecycle_events.append(("start", stream)),
    )
    monkeypatch.setattr(
        "rag.query.service.log_query_complete",
        lambda _ctx, *, stream: lifecycle_events.append(("complete", stream)),
    )
    service = LocalRagService(
        config=Settings(document_repository="memory"),
        ollama=object(),
        qdrant=object(),
        chat_history_repo=history,
        conflict_checker=object(),
        artifact_job_service=artifact_jobs,
    )

    response = service.answer_query(
        QueryRequest(query="Create a PDF report about quarterly risk"),
        _user(),
    )

    assert response.artifact_job is not None
    assert lifecycle_events == [("start", False), ("complete", False)]
    saved = history.get_session(
        session_id=response.session_id,
        user_id="user-1",
        permission_version=1,
    )
    assert saved is not None
    assert len(saved.turns) == 2


class _ArtifactJobService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def submit(self, **kwargs) -> ArtifactJobSummary:
        self.calls.append(kwargs)
        return ArtifactJobSummary(
            id="job-1",
            status="queued",
            stage="queued",
            progress_pct=0,
            stage_label="Queued",
            stage_detail="Waiting for the document generation worker",
            stage_progress=None,
            requested_formats=list(kwargs["formats"]),
        )


class _Resolver:
    def __init__(self) -> None:
        self.calls = 0

    def generate_routing_json(self, **_kwargs) -> str:
        self.calls += 1
        return json.dumps(
            {
                "relation": "follow_up",
                "standalone_query": "create a pdf report about quarterly risk",
                "antecedent_turn_ids": ["previous-user"],
                "clarification_question": None,
            }
        )


class _UnexpectedResolver:
    def generate_routing_json(self, **_kwargs) -> str:
        raise AssertionError("context resolver should not be called")


def _service(*, artifact_jobs, history, ollama) -> LocalRagService:
    return LocalRagService(
        config=Settings(document_repository="memory"),
        ollama=ollama,
        qdrant=object(),
        chat_history_repo=history,
        conflict_checker=object(),
        artifact_job_service=artifact_jobs,
    )


def _save_exchange(
    history: InMemoryChatHistoryRepository,
    *,
    query: str,
    sources: list[dict[str, object]] | None = None,
) -> None:
    history.append_completed_turn(
        user_id="user-1",
        permission_version=1,
        session_id="session-1",
        title=query,
        user_turn={
            "id": "previous-user",
            "role": "user",
            "content": query,
        },
        assistant_turn={
            "id": "previous-assistant",
            "role": "assistant",
            "question": query,
            "response": {
                "answer": "Quarterly risk is elevated.",
                "intent": "factual_simple",
                "sources": sources or [],
                "faithfulness_score": 1.0,
                "faithfulness_status": "checked",
                "degraded": False,
            },
        },
    )


def _source() -> dict[str, object]:
    return {
        "doc_id": "doc-1",
        "doc_title": "Quarterly Risk.pdf",
        "chunk_id": "chunk-1",
        "page": 2,
        "excerpt": "Quarterly risk is elevated because vendor exposure increased.",
        "group_path": "/",
    }


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.test",
        account_type="platform_admin",
        group_paths=("/",),
        permission_version=1,
    )
