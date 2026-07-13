from __future__ import annotations

import pytest

from rag.ingestion.config import WorkerConfig


def test_worker_uses_canonical_runtime_defaults_without_duplicate_inference_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_HTTP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("GRAPHRAG_ENABLED", raising=False)

    config = WorkerConfig.from_env()

    assert config.http_timeout_seconds == 180.0
    assert config.graphrag_enabled is True
    assert not hasattr(config.local_embeddings, "provider")
    assert not hasattr(config.local_embeddings, "ollama_base_url")
    assert not hasattr(config.local_embeddings, "ollama_chat_model")
    assert not hasattr(config.local_embeddings, "ollama_embed_model")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GRAPHRAG_EXTRACTION_CONCURRENCY", "0"),
        ("INGEST_WORKER_BOOT_CONCURRENCY", "11"),
        ("LAYERED_DOCLING_MAX_PAGES", "0"),
        ("DOCLING_CONVERT_TIMEOUT_SECONDS", "-1"),
        ("SCANNED_VISUAL_MIN_AREA_RATIO", "-0.1"),
        ("QDRANT_UPSERT_BATCH_SIZE", "0"),
    ],
)
def test_worker_rejects_numeric_values_that_were_previously_clamped(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        WorkerConfig.from_env()


def test_worker_rejects_invalid_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPHRAG_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="boolean-like"):
        WorkerConfig.from_env()


def test_worker_rejects_invalid_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_MODEL_PROVIDER", "unsupported")

    with pytest.raises(ValueError, match="RAG_MODEL_PROVIDER"):
        WorkerConfig.from_env()
