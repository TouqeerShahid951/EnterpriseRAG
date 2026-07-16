from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api import readiness
from apps.api.main import create_app
from apps.api.readiness import _failed_dependency, probe_readiness
from rag.query.configuration.models import RagConfigRecord


def test_readiness_reflects_dependency_health() -> None:
    app = create_app()
    client = TestClient(app)

    app.dependency_overrides[probe_readiness] = lambda: ()
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "ready": True,
        "detail": "Required dependencies are available.",
    }

    app.dependency_overrides[probe_readiness] = lambda: ("redis",)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "ready": False,
        "detail": "Unavailable dependencies: redis.",
    }

    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_probe_returns_only_failed_dependency_names() -> None:
    def fail() -> None:
        raise ConnectionError("must not leak")

    assert _failed_dependency(("redis", fail)) == "redis"
    assert _failed_dependency(("postgres", lambda: None)) is None


def test_probe_uses_effective_workspace_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rag_config = RagConfigRecord(
        base_url="http://models.test",
        chat_model="chat",
        embed_model="workspace-dense",
        embedding_provider="fastembed",
        faithfulness_model=None,
        chat_timeout_seconds=2,
        embed_timeout_seconds=2,
        reranker_model="workspace-reranker",
    )
    checked_models: list[str] = []

    monkeypatch.setattr(readiness, "_load_effective_rag_config", lambda: rag_config)
    monkeypatch.setattr(readiness, "_check_redis", lambda: None)
    monkeypatch.setattr(readiness, "_check_qdrant", lambda: None)
    monkeypatch.setattr(
        readiness,
        "has_fastembed_model_cache",
        lambda _cache, model: checked_models.append(model) or True,
    )
    monkeypatch.setattr(
        readiness,
        "has_complete_fastembed_model_cache",
        lambda _cache, model, **_kwargs: checked_models.append(model) or True,
    )

    assert readiness.probe_readiness() == ()
    assert checked_models == [
        "workspace-dense",
        readiness.settings.rag_sparse_model,
        "workspace-reranker",
    ]
