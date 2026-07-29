from datetime import UTC, datetime

import pytest

from rag.query.configuration import service as rag_config_service
from rag.query.configuration.service import RagConfigValidationError, validate_rag_config
from rag.query.configuration.models import RagConfigRecord


class _Qdrant:
    def current_vector_size(self):
        return None


class _Settings:
    qdrant_url = "http://qdrant:6333"
    qdrant_collection = "documents"
    rag_http_timeout_seconds = 45
    rag_dense_cache_dir = "/models/fastembed"
    rag_reranker_cache_dir = "/models/fastembed"
    rag_reranker_device = "auto"


def test_fastembed_embedding_provider_uses_local_model_catalog(monkeypatch) -> None:
    reranker_calls = []

    def fake_request_json(base_url, path, **kwargs):
        if path == "/api/tags":
            return {"models": [{"name": "llama3.1:8b"}]}
        if path == "/api/chat":
            return {"message": {"content": '{"status":"ok"}'}}
        raise AssertionError(f"unexpected network call: {base_url} {path}")

    monkeypatch.setattr(rag_config_service, "request_json", fake_request_json)
    monkeypatch.setattr(rag_config_service, "list_supported_dense_models", lambda **_: ["nomic-ai/nomic-embed-text-v1.5-Q"])
    monkeypatch.setattr(
        rag_config_service,
        "embed_dense_texts",
        lambda texts, *, model_name, cache_dir: [[0.1, 0.2, 0.3] for _ in texts],
    )
    monkeypatch.setattr(
        rag_config_service,
        "rank_passages",
        lambda query, passages, **kwargs: (
            reranker_calls.append((query, passages, kwargs)) or [(0, 1.0)]
        ),
    )
    monkeypatch.setattr(rag_config_service, "datetime", type("Clock", (), {"now": staticmethod(lambda tz: datetime(2026, 1, 1, tzinfo=UTC))}))

    result = validate_rag_config(
        RagConfigRecord(
            provider="ollama",
            embedding_provider="fastembed",
            base_url="http://ollama:11434",
            embedding_base_url="http://ollama:11434",
            chat_model="llama3.1:8b",
            embed_model="nomic-ai/nomic-embed-text-v1.5-Q",
            faithfulness_model=None,
            chat_timeout_seconds=180,
            embed_timeout_seconds=45,
        ),
        app_config=_Settings(),  # type: ignore[arg-type]
        qdrant=_Qdrant(),  # type: ignore[arg-type]
    )

    assert result.embedding_models == ["nomic-ai/nomic-embed-text-v1.5-Q"]
    assert result.embedding_dimension == 3
    assert reranker_calls == [
        (
            "reranker inference health check",
            ["reranker inference health check"],
            {
                "model_name": "jinaai/jina-reranker-v1-turbo-en",
                "cache_dir": "/models/fastembed",
                "device": "auto",
            },
        )
    ]


def test_rag_config_validation_rejects_failed_reranker_inference(monkeypatch) -> None:
    def fail_reranker(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("ModelProto does not have a graph")

    monkeypatch.setattr(rag_config_service, "rank_passages", fail_reranker)

    with pytest.raises(RagConfigValidationError) as captured:
        validate_rag_config(
            RagConfigRecord(
                provider="ollama",
                embedding_provider="fastembed",
                base_url="http://ollama:11434",
                embedding_base_url="http://ollama:11434",
                chat_model="llama3.1:8b",
                embed_model="nomic-ai/nomic-embed-text-v1.5-Q",
                faithfulness_model=None,
                chat_timeout_seconds=180,
                embed_timeout_seconds=45,
            ),
            app_config=_Settings(),  # type: ignore[arg-type]
            qdrant=_Qdrant(),  # type: ignore[arg-type]
        )

    error = captured.value
    assert error.code == "reranker_unavailable"
    assert error.status_code == 503
    assert "jinaai/jina-reranker-v1-turbo-en" in error.message
    assert isinstance(error.__cause__, RuntimeError)
