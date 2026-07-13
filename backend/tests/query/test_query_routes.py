"""Behavioral characterization for the public query HTTP boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.artifact_jobs.service import ArtifactJobActionError
from rag.auth.dependencies import require_current_user
from rag.auth.identity_models import GroupRecord, UserRecord
from rag.auth.identity_repository import get_identity_repository
from rag.connectors.repositories import (
    InMemoryConnectorProfileRepository,
    get_connector_profile_repository,
)
from rag.core.config import settings
from rag.ingestion.folders.adapters.memory import InMemoryFolderScheduleRepository
from rag.ingestion.folders.dependencies import get_folder_schedule_repository
from rag.query import execution_routes, routes as query_routes
from rag.query.adapters.chat_history_memory import InMemoryChatHistoryRepository
from rag.query.chat_history_repository import get_chat_history_repository
from rag.query.http import ServiceRequestError
from rag.query.schemas import QueryRequest, QueryStreamEvent, RAGResponse
from rag.query.service import get_local_rag_service


CSRF_TOKEN = "query-route-csrf"


def _user(
    *,
    account_type: str = "member",
    group_paths: tuple[str, ...] = ("/ops",),
    permission_version: int = 3,
) -> UserRecord:
    return UserRecord(
        id="user-1",
        email="user@example.test",
        name="Query User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=permission_version,
        group_paths=group_paths,
    )


@dataclass
class StubIdentityRepository:
    groups: tuple[str, ...] = ("/ops",)

    def list_groups(self) -> list[GroupRecord]:
        return [
            GroupRecord(path=path, name=path.strip("/").title()) for path in self.groups
        ]


class RecordingRagService:
    def __init__(
        self,
        *,
        response: RAGResponse | None = None,
        error: Exception | None = None,
        stream_events: tuple[QueryStreamEvent, ...] = (),
        stream_error: Exception | None = None,
    ) -> None:
        self.response = response or _response()
        self.error = error
        self.stream_events = stream_events
        self.stream_error = stream_error
        self.answer_calls: list[tuple[QueryRequest, object]] = []
        self.stream_calls: list[tuple[QueryRequest, object]] = []

    def answer_query(self, request: QueryRequest, user: object) -> RAGResponse:
        self.answer_calls.append((request, user))
        if self.error is not None:
            raise self.error
        return self.response

    def stream_query(
        self,
        request: QueryRequest,
        user: object,
        *,
        cancellation_token: object | None = None,
    ) -> Iterator[QueryStreamEvent]:
        _ = cancellation_token
        self.stream_calls.append((request, user))

        def events() -> Iterator[QueryStreamEvent]:
            yield from self.stream_events
            if self.stream_error is not None:
                raise self.stream_error

        return events()


class RecordingHistoryRepository(InMemoryChatHistoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.get_calls: list[dict[str, object]] = []

    def get_session(self, *, session_id: str, user_id: str, permission_version: int):
        self.get_calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "permission_version": permission_version,
            }
        )
        return super().get_session(
            session_id=session_id,
            user_id=user_id,
            permission_version=permission_version,
        )


def test_run_query_checks_csrf_before_invoking_service() -> None:
    service = RecordingRagService()
    client = _execution_client(service=service)

    response = client.post("/query", json={"query": "What is the policy?"})

    assert response.status_code == 403
    assert response.json() == {
        "detail": {
            "code": "csrf_required",
            "message": "Valid CSRF token required.",
        }
    }
    assert service.answer_calls == []


@pytest.mark.parametrize(
    ("user", "payload", "expected_status", "expected_code"),
    [
        (
            _user(account_type="reviewer"),
            {"query": "What is the policy?"},
            403,
            "query_role_forbidden",
        ),
        (
            _user(group_paths=("/ops",)),
            {"query": "What is the policy?", "group_path": "/finance"},
            403,
            "query_group_forbidden",
        ),
        (
            _user(group_paths=("/ops",)),
            {"query": "What is the policy?", "group_path": "/../ops"},
            400,
            "invalid_query_group",
        ),
        (
            _user(account_type="platform_admin", group_paths=()),
            {"query": "What is the policy?", "group_path": "/missing"},
            400,
            "query_group_not_found",
        ),
    ],
)
def test_run_query_preserves_role_and_group_rejections(
    user: UserRecord,
    payload: dict[str, object],
    expected_status: int,
    expected_code: str,
) -> None:
    service = RecordingRagService()
    client = _execution_client(service=service, user=user)

    response = client.post("/query", json=payload, **_csrf_request())

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert service.answer_calls == []


@pytest.mark.parametrize(
    ("source_id", "expected_status", "expected_code"),
    [
        ("profile:raw", 400, "invalid_query_source"),
        ("connector_catalog:missing", 403, "query_source_forbidden"),
    ],
)
def test_run_query_maps_source_access_errors(
    source_id: str, expected_status: int, expected_code: str
) -> None:
    service = RecordingRagService()
    client = _execution_client(service=service)

    response = client.post(
        "/query",
        json={"query": "Count cases", "query_source_id": source_id},
        **_csrf_request(),
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert service.answer_calls == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            ServiceRequestError("ollama", "connection refused"),
            503,
            {
                "code": "ollama_unavailable",
                "message": "ollama unavailable: connection refused",
            },
        ),
        (
            ArtifactJobActionError(
                "artifact_enqueue_failed", "Document generation could not be queued."
            ),
            409,
            {
                "code": "artifact_enqueue_failed",
                "message": "Document generation could not be queued.",
            },
        ),
    ],
)
def test_run_query_preserves_application_error_mapping(
    error: Exception, expected_status: int, expected_detail: dict[str, str]
) -> None:
    client = _execution_client(service=RecordingRagService(error=error))

    response = client.post(
        "/query", json={"query": "What is the policy?"}, **_csrf_request()
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


def test_get_chat_session_scopes_lookup_to_permission_version() -> None:
    user = _user(permission_version=7)
    repo = RecordingHistoryRepository()
    repo.append_completed_turn(
        user_id=user.id,
        permission_version=6,
        session_id="session-1",
        title="Old permissions",
        user_turn={"role": "user"},
        assistant_turn={"role": "assistant"},
    )
    client = _history_client(repo=repo, user=user)

    response = client.get("/query/sessions/session-1")

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": "chat_session_not_found",
            "message": "Chat session was not found.",
        }
    }
    assert repo.get_calls == [
        {
            "session_id": "session-1",
            "user_id": user.id,
            "permission_version": 7,
        }
    ]


def test_completed_query_is_saved_under_current_permission_version() -> None:
    user = _user(permission_version=7)
    repo = RecordingHistoryRepository()
    service = RecordingRagService(response=_response(answer="Grounded answer"))
    client = _execution_client(service=service, user=user, history_repo=repo)

    response = client.post(
        "/query",
        json={"query": "  What is the policy?  ", "group_path": "/ops"},
        **_csrf_request(),
    )

    assert response.status_code == 200
    saved = repo.get_session(
        session_id="session-1", user_id=user.id, permission_version=7
    )
    assert saved is not None
    assert saved.title == "What is the policy?"
    assert [turn["role"] for turn in saved.turns] == ["user", "assistant"]
    assert saved.turns[0]["content"] == "What is the policy?"
    assert saved.turns[1]["response"]["answer"] == "Grounded answer"
    assert saved.turns[1]["groupPath"] == "/ops"


def test_stream_done_and_verified_events_persist_the_final_response() -> None:
    user = _user(permission_version=7)
    repo = RecordingHistoryRepository()
    done = _response(answer="Initial answer")
    verified = _response(answer="Verified answer")
    service = RecordingRagService(
        stream_events=(
            QueryStreamEvent(event="done", data=done.model_dump(mode="json")),
            QueryStreamEvent(event="verified", data=verified.model_dump(mode="json")),
        )
    )
    client = _execution_client(service=service, user=user, history_repo=repo)

    response = client.post(
        "/query/stream",
        json={"query": "What is the policy?"},
        **_csrf_request(),
    )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert "event: verified" in response.text
    saved = repo.get_session(
        session_id="session-1", user_id=user.id, permission_version=7
    )
    assert saved is not None
    assert saved.turns[1]["response"]["answer"] == "Verified answer"


def test_stream_maps_service_failure_to_an_sse_error() -> None:
    service = RecordingRagService(
        stream_error=ServiceRequestError("qdrant", "timed out")
    )
    client = _execution_client(service=service)

    response = client.post(
        "/query/stream",
        json={"query": "What is the policy?"},
        **_csrf_request(),
    )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code": "qdrant_unavailable"' in response.text
    assert '"message": "qdrant unavailable: timed out"' in response.text


def test_stream_disconnect_cancels_and_closes_the_query_iterator() -> None:
    iterator = ClosableQueryIterator()
    service = DisconnectAwareRagService(iterator)
    request = DisconnectingRequest()
    user = _user()

    async def exercise() -> list[str | bytes]:
        response = await execution_routes.stream_query(
            QueryRequest(query="What is the policy?"),
            request,  # type: ignore[arg-type]
            user=user,
            identity_repo=StubIdentityRepository(),  # type: ignore[arg-type]
            chat_history_repo=RecordingHistoryRepository(),
            schedule_repo=InMemoryFolderScheduleRepository(),
            connector_profile_repo=InMemoryConnectorProfileRepository(),
            rag_service=service,  # type: ignore[arg-type]
        )
        return [chunk async for chunk in response.body_iterator]

    assert asyncio.run(exercise()) == []
    assert service.cancellation_token is not None
    assert service.cancellation_token.is_cancelled
    assert iterator.closed


class ClosableQueryIterator:
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self) -> "ClosableQueryIterator":
        return self

    def __next__(self) -> QueryStreamEvent:
        return QueryStreamEvent(event="token", data={"text": "unused"})

    def close(self) -> None:
        self.closed = True


class DisconnectAwareRagService:
    def __init__(self, iterator: ClosableQueryIterator) -> None:
        self.iterator = iterator
        self.cancellation_token: Any | None = None

    def stream_query(
        self,
        request: QueryRequest,
        user: object,
        *,
        cancellation_token: Any | None = None,
    ) -> ClosableQueryIterator:
        _ = request, user
        self.cancellation_token = cancellation_token
        return self.iterator


class DisconnectingRequest:
    method = "POST"
    cookies = {settings.csrf_cookie_name: CSRF_TOKEN}
    headers = {"X-CSRF-Token": CSRF_TOKEN}

    async def is_disconnected(self) -> bool:
        return True


def _execution_client(
    *,
    service: object,
    user: UserRecord | None = None,
    history_repo: object | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(query_routes.router)
    app.dependency_overrides[require_current_user] = lambda: user or _user()
    app.dependency_overrides[get_identity_repository] = lambda: StubIdentityRepository()
    app.dependency_overrides[get_chat_history_repository] = lambda: (
        history_repo or RecordingHistoryRepository()
    )
    app.dependency_overrides[get_folder_schedule_repository] = lambda: (
        InMemoryFolderScheduleRepository()
    )
    app.dependency_overrides[get_connector_profile_repository] = lambda: (
        InMemoryConnectorProfileRepository()
    )
    app.dependency_overrides[get_local_rag_service] = lambda: service
    client = TestClient(app)
    client.cookies.set(settings.csrf_cookie_name, CSRF_TOKEN)
    return client


def _history_client(*, repo: object, user: UserRecord | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(query_routes.router)
    app.dependency_overrides[require_current_user] = lambda: user or _user()
    app.dependency_overrides[get_chat_history_repository] = lambda: repo
    return TestClient(app)


def _csrf_request() -> dict[str, object]:
    return {
        "headers": {"X-CSRF-Token": CSRF_TOKEN},
    }


def _response(*, answer: str = "Answer") -> RAGResponse:
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
