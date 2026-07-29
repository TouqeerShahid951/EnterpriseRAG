from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api import main as api_main
from apps.api.readiness import probe_readiness
from rag.auth.identity_repository import get_identity_repository
from rag.query.configuration.models import RagConfigRecord
from rag.query.runtime_warmup import QueryRuntimeWarmupError


def _rag_config() -> RagConfigRecord:
    return RagConfigRecord(
        base_url="http://models.test",
        chat_model="chat-model",
        embed_model="dense-model",
        embedding_provider="fastembed",
        faithfulness_model=None,
        chat_timeout_seconds=2,
        embed_timeout_seconds=2,
        reranker_model="jinaai/jina-reranker-v1-turbo-en",
    )


def _stub_startup(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    warmup_error: Exception | None = None,
) -> object:
    rag_config = _rag_config()
    monkeypatch.setattr(
        api_main,
        "ensure_postgres_schema",
        lambda _settings: events.append("schema"),
    )
    monkeypatch.setattr(
        api_main,
        "ensure_initial_platform_admin",
        lambda *_args, **_kwargs: events.append("admin"),
    )
    monkeypatch.setattr(
        api_main,
        "effective_rag_config",
        lambda **_kwargs: events.append("config") or rag_config,
    )

    def warmup(**kwargs: object) -> None:
        assert kwargs == {
            "app_settings": api_main.settings,
            "rag_config": rag_config,
        }
        events.append("warmup")
        if warmup_error is not None:
            raise warmup_error

    monkeypatch.setattr(api_main, "warm_query_fastembed_runtime", warmup)
    monkeypatch.setattr(
        api_main,
        "close_postgres_pools",
        lambda: events.append("close"),
    )
    app = api_main.create_app()
    app.dependency_overrides[get_identity_repository] = lambda: object()
    app.dependency_overrides[probe_readiness] = lambda: ()
    return app


def test_api_warms_query_runtime_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    app = _stub_startup(monkeypatch, events)

    with TestClient(app) as client:  # type: ignore[arg-type]
        assert events == ["schema", "admin", "config", "warmup"]
        assert client.get("/health/ready").status_code == 200

    assert events == ["schema", "admin", "config", "warmup", "close"]


def test_api_startup_fails_before_readiness_when_warmup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    error = QueryRuntimeWarmupError("configured sparse model is corrupt")
    app = _stub_startup(monkeypatch, events, warmup_error=error)

    with pytest.raises(QueryRuntimeWarmupError, match="sparse model is corrupt"):
        with TestClient(app):  # type: ignore[arg-type]
            pytest.fail("application must not become ready")

    assert events == ["schema", "admin", "config", "warmup", "close"]
