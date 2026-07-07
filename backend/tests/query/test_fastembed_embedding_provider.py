from datetime import UTC, datetime

from rag.query import rag_config_service
from rag.query.rag_config_service import validate_rag_config
from rag.repositories.rag_config_models import RagConfigRecord


class _Qdrant:
    def current_vector_size(self):
        return None


class _Settings:
    qdrant_url = "http://qdrant:6333"
    qdrant_collection = "documents"
    rag_http_timeout_seconds = 45
    rag_dense_cache_dir = "/models/fastembed"


def test_fastembed_embedding_provider_uses_local_model_catalog(monkeypatch) -> None:
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
