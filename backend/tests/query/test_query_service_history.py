from __future__ import annotations

from rag.auth.context import UserContext
from rag.core.config import Settings
from rag.ingestion.adapters.configuration_memory import InMemoryIngestConfigRepository
from rag.ingestion.configuration import IngestConfigRecord
from rag.query.adapters.chat_history_memory import InMemoryChatHistoryRepository
from rag.query.retrieval.retrieval_trace import RetrievalTrace
from rag.query.schemas import QueryRequest, QueryStreamEvent, RAGResponse
from rag.query.service import LocalRagService, QueryExecutionResult


def test_answer_query_persists_the_completed_exchange() -> None:
    history = InMemoryChatHistoryRepository()
    service = _service(history)
    response = _response(answer="Grounded answer")
    service.execute_query = lambda *_args, **_kwargs: QueryExecutionResult(  # type: ignore[method-assign]
        response=response,
        retrieval_trace=RetrievalTrace(),
    )

    result = service.answer_query(
        QueryRequest(
            query="  What is the policy?  ",
            session_id="session-1",
            client_request_id="request-1",
            reply_to_turn_id="assistant-earlier",
            group_path="/ops",
        ),
        _user(),
    )

    assert result is response
    saved = history.get_session(
        session_id="session-1",
        user_id="user-1",
        permission_version=1,
    )
    assert saved is not None
    assert saved.turns[0]["content"] == "What is the policy?"
    assert saved.turns[0]["id"] == "user-request-1"
    assert saved.turns[0]["replyToTurnId"] == "assistant-earlier"
    assert saved.turns[1]["replyToTurnId"] == "assistant-earlier"
    assert saved.turns[1]["response"]["answer"] == "Grounded answer"


def test_stream_persists_before_done_and_updates_verified_response(monkeypatch) -> None:
    history = RecordingHistoryRepository()
    service = _service(history)
    initial = _response(answer="Initial answer")
    verified = _response(answer="Verified answer")

    def fake_stream_graph(_ctx, _nodes):
        yield QueryStreamEvent(event="token", data={"text": "Unverified draft", "draft": True})
        yield QueryStreamEvent(event="done", data=initial.model_dump(mode="json"))
        yield QueryStreamEvent(event="verified", data=verified.model_dump(mode="json"))

    monkeypatch.setattr("rag.query.service.stream_graph", fake_stream_graph)
    events = service.stream_query(
        QueryRequest(
            query="What is the policy?",
            session_id="session-1",
            client_request_id="request-1",
        ),
        _user(),
    )

    draft = next(events)
    assert draft.event == "token" and draft.data["draft"] is True
    assert history.appended is False
    done = next(events)

    assert done.event == "done"
    assert history.appended is True
    assert next(events).event == "verified"
    saved = history.get_session(
        session_id="session-1",
        user_id="user-1",
        permission_version=1,
    )
    assert saved is not None
    assert saved.turns[1]["response"]["answer"] == "Verified answer"


def test_source_selection_continues_the_saved_clarification_turn() -> None:
    history = InMemoryChatHistoryRepository()
    service = _service(history)
    clarification = RAGResponse.model_validate(
        {
            **_response(answer="Choose a database").model_dump(mode="json"),
            "answer_status": "clarification",
            "source_clarification": {
                "question": "Which database?",
                "options": [
                    {
                        "source_id": "connector_catalog:catalog-1",
                        "name": "Cases",
                    }
                ],
            },
        }
    )
    final = _response(answer="There are three cases")
    responses = iter((clarification, final))
    service.execute_query = lambda *_args, **_kwargs: QueryExecutionResult(  # type: ignore[method-assign]
        response=next(responses),
        retrieval_trace=RetrievalTrace(),
    )

    service.answer_query(
        QueryRequest(
            query="How many cases are there?",
            session_id="session-1",
            client_request_id="request-1",
        ),
        _user(),
    )
    service.answer_query(
        QueryRequest(
            query="How many cases are there?",
            session_id="session-1",
            client_request_id="request-1",
            source_mode="db_only",
            query_source_id="connector_catalog:catalog-1",
            continue_source_clarification=True,
        ),
        _user(),
    )

    saved = history.get_session(
        session_id="session-1",
        user_id="user-1",
        permission_version=1,
    )
    assert saved is not None
    assert len(saved.turns) == 2
    assert saved.turns[1]["id"] == "request-1"
    assert saved.turns[1]["response"]["answer"] == "There are three cases"


def test_graph_query_requires_deployment_and_workspace_enrichment() -> None:
    config_repo = InMemoryIngestConfigRepository()
    config_repo.save_active(IngestConfigRecord(graph_enrichment_enabled=False))

    service = LocalRagService(
        config=Settings(document_repository="memory", graphrag_enabled=True),
        ollama=object(),  # type: ignore[arg-type]
        qdrant=object(),  # type: ignore[arg-type]
        chat_history_repo=InMemoryChatHistoryRepository(),
        conflict_checker=object(),  # type: ignore[arg-type]
        artifact_job_service=object(),  # type: ignore[arg-type]
        ingest_config_repo=config_repo,
    )

    assert service.nodes.graph_enabled is False


class RecordingHistoryRepository(InMemoryChatHistoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.appended = False

    def append_completed_turn(self, **kwargs):
        result = super().append_completed_turn(**kwargs)
        self.appended = True
        return result


def _service(history: InMemoryChatHistoryRepository) -> LocalRagService:
    return LocalRagService(
        config=Settings(document_repository="memory"),
        ollama=object(),  # type: ignore[arg-type]
        qdrant=object(),  # type: ignore[arg-type]
        chat_history_repo=history,
        conflict_checker=object(),  # type: ignore[arg-type]
        artifact_job_service=object(),  # type: ignore[arg-type]
    )


def test_analytics_initialization_failure_does_not_prevent_query_service(monkeypatch, caplog):
    def unavailable(_config):
        raise RuntimeError("synthetic sensitive database failure")

    monkeypatch.setattr("rag.query.service.analytics_repository_from_config", unavailable)
    service = _service(InMemoryChatHistoryRepository())
    assert service.analytics_recorder is None
    assert service.nodes is not None
    assert "capture unavailable" in caplog.text
    assert "sensitive" not in caplog.text


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.test",
        account_type="platform_admin",
        group_paths=("/ops",),
        permission_version=1,
    )


def _response(*, answer: str) -> RAGResponse:
    return RAGResponse(
        trace_id="trace-1",
        answer=answer,
        conflict_flag=False,
        faithfulness_score=1.0,
        intent="factual_simple",
        session_id="session-1",
        latency_ms=5,
        degraded=False,
    )
