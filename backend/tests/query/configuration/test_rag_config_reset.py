from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.query.configuration import routes as admin_rag_config_routes
from rag.auth.dependencies import require_platform_admin_user
from rag.auth.identity_models import UserRecord
from rag.auth.identity_repository import get_identity_repository
from rag.auth.issued_tokens import create_auth_tokens
from rag.auth.refresh_sessions import InMemoryRefreshSessionStore, auth_idle_ttl_seconds, get_refresh_session_store
from rag.core.config import Settings, settings
from rag.query.adapters.rag_config_memory import InMemoryRagConfigRepository
from rag.query.adapters import rag_config_postgres
from rag.query.adapters.rag_config_postgres import PostgresRagConfigRepository
from rag.query.configuration.mapping import rag_config_response
from rag.query.configuration.models import ACTIVE_CONFIG_KEY, RagConfigRecord
from rag.query.configuration.repository import effective_rag_config, get_rag_config_repository


def test_saved_workspace_config_takes_precedence_over_environment_until_deleted() -> None:
    config = Settings(
        rag_model_provider="ollama",
        ollama_base_url="http://environment:11434",
        ollama_chat_model="environment-chat",
        rag_reasoning_timeout_seconds=41,
        rag_faithfulness_timeout_seconds=39,
    )
    repo = InMemoryRagConfigRepository()
    repo.save_active(_workspace_record())

    saved = effective_rag_config(config=config, repo=repo)

    assert saved.source == "workspace"
    assert saved.chat_model == "workspace-chat"
    assert saved.sql_generation_model == "workspace-sql"
    assert saved.evidence_gate_policy == "never"
    assert saved.faithfulness_policy == "never"
    assert saved.reasoning_timeout_seconds == 31
    assert saved.faithfulness_timeout_seconds == 29

    repo.delete_active()
    fallback = effective_rag_config(config=config, repo=repo)

    assert fallback.source == "env"
    assert fallback.chat_model == "environment-chat"
    assert fallback.sql_generation_model is None
    assert fallback.base_url == "http://environment:11434"
    assert fallback.evidence_gate_policy == "adaptive"
    assert fallback.faithfulness_policy == "adaptive"
    assert fallback.reasoning_timeout_seconds == 41
    assert fallback.faithfulness_timeout_seconds == 39


def test_reset_route_deletes_saved_config_and_returns_environment_fallback() -> None:
    repo = InMemoryRagConfigRepository()
    expected = rag_config_response(effective_rag_config(repo=repo)).model_dump(mode="json")
    repo.save_active(_workspace_record())
    client = _admin_client(repo)

    response = client.delete("/admin/rag-config")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.json()["source"] == "env"
    assert repo.get_active() is None


def test_reset_route_is_idempotent_without_saved_config() -> None:
    repo = InMemoryRagConfigRepository()
    client = _admin_client(repo)

    first = client.delete("/admin/rag-config")
    second = client.delete("/admin/rag-config")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert second.json()["source"] == "env"


def test_reset_route_preserves_saved_config_when_environment_fallback_is_invalid(
    monkeypatch,
) -> None:
    repo = InMemoryRagConfigRepository()
    repo.save_active(_workspace_record())
    monkeypatch.setattr(settings, "rag_chat_base_url", "https://invalid.example")
    client = _admin_client(repo, raise_server_exceptions=False)

    response = client.delete("/admin/rag-config")

    assert response.status_code == 500
    assert repo.get_active() is not None
    assert repo.get_active().source == "workspace"


def test_reset_route_requires_authentication() -> None:
    repo = InMemoryRagConfigRepository()
    repo.save_active(_workspace_record())
    app = FastAPI()
    app.include_router(admin_rag_config_routes.router)
    app.dependency_overrides[get_rag_config_repository] = lambda: repo

    response = TestClient(app).delete("/admin/rag-config")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth_required"
    assert repo.get_active() is not None


def test_reset_route_rejects_non_platform_global_admin() -> None:
    repo = InMemoryRagConfigRepository()
    repo.save_active(_workspace_record())
    user = _user(account_type="system_admin")
    access_token, refresh_token, csrf_token = create_auth_tokens(user)
    sessions = InMemoryRefreshSessionStore()
    sessions.remember(
        user_id=user.id,
        refresh_token=refresh_token,
        ttl_seconds=auth_idle_ttl_seconds(),
    )
    app = FastAPI()
    app.include_router(admin_rag_config_routes.router)
    app.dependency_overrides[get_identity_repository] = lambda: _IdentityRepository(user)
    app.dependency_overrides[get_refresh_session_store] = lambda: sessions
    app.dependency_overrides[get_rag_config_repository] = lambda: repo
    client = TestClient(app)
    client.cookies.set(settings.access_cookie_name, access_token)
    client.cookies.set(settings.refresh_cookie_name, refresh_token)
    client.cookies.set(settings.csrf_cookie_name, csrf_token)

    response = client.delete(
        "/admin/rag-config",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "platform_admin_required"
    assert repo.get_active() is not None


def test_postgres_delete_targets_only_the_active_singleton(monkeypatch) -> None:
    repo = PostgresRagConfigRepository("postgresql://unused")
    calls: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(repo, "_ensure_table", lambda: None)
    monkeypatch.setattr(
        repo,
        "_execute_optional",
        lambda query, params: calls.append((query, params)),
    )

    repo.delete_active()

    assert len(calls) == 1
    query, params = calls[0]
    assert "DELETE FROM workspace_rag_config" in query
    assert "config_key = %s" in query
    assert params == (ACTIVE_CONFIG_KEY,)


def test_postgres_save_persists_ai_gate_policies(monkeypatch) -> None:
    repo = PostgresRagConfigRepository("postgresql://unused")
    calls: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(repo, "_ensure_table", lambda: None)
    monkeypatch.setattr(
        repo,
        "_execute_one",
        lambda query, params: calls.append((query, params)) or {},
    )
    monkeypatch.setattr(rag_config_postgres, "record_from_row", lambda row: row)

    repo.save_active(_workspace_record())

    query, params = calls[0]
    assert "evidence_gate_policy" in query
    assert "faithfulness_policy" in query
    assert "routing_timeout_seconds" in query
    assert "reasoning_timeout_seconds" in query
    assert "faithfulness_timeout_seconds" in query
    assert "sql_generation_model" in query
    assert query.count("%s") == len(params)
    assert 7 in params
    assert "never" in params
    assert "workspace-sql" in params


def _admin_client(
    repo: InMemoryRagConfigRepository,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    user = _user(account_type="platform_admin")
    app = FastAPI()
    app.include_router(admin_rag_config_routes.router)
    app.dependency_overrides[require_platform_admin_user] = lambda: user
    app.dependency_overrides[get_rag_config_repository] = lambda: repo
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _user(*, account_type: str) -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email=f"{account_type}@example.test",
        name=account_type.replace("_", " ").title(),
        password_hash="hash",
        is_active=True,
        account_type=account_type,
        clearance_level="COSMIC_TOP_SECRET",
        must_change_password=False,
        permission_version=1,
        group_paths=(),
    )


class _IdentityRepository:
    def __init__(self, user: UserRecord) -> None:
        self.user = user

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return self.user if self.user.id == user_id else None


def _workspace_record() -> RagConfigRecord:
    return RagConfigRecord(
        provider="ollama",
        embedding_provider="ollama",
        base_url="http://workspace:11434",
        embedding_base_url="http://workspace:11434",
        chat_model="workspace-chat",
        embed_model="workspace-embed",
        sql_generation_model="workspace-sql",
        faithfulness_model=None,
        evidence_gate_policy="never",
        faithfulness_policy="never",
        chat_timeout_seconds=30,
        routing_timeout_seconds=7,
        reasoning_timeout_seconds=31,
        faithfulness_timeout_seconds=29,
        embed_timeout_seconds=15,
    )
