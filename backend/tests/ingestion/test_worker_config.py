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
    assert config.ingest_task_name == "apps.ingestion.tasks.ingest_document"
    assert (
        config.graphrag_index_task_name
        == "apps.ingestion.tasks.index_document_graphrag"
    )
    assert (
        config.graphrag_partition_rebuild_task_name
        == "apps.ingestion.tasks.rebuild_graphrag_partition"
    )
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


def test_worker_reads_configured_task_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGEST_TASK_NAME", "custom.ingest.run")
    monkeypatch.setenv("GRAPHRAG_INDEX_TASK_NAME", "custom.graphrag.index")
    monkeypatch.setenv(
        "GRAPHRAG_PARTITION_REBUILD_TASK_NAME",
        "custom.graphrag.rebuild",
    )

    config = WorkerConfig.from_env()

    assert config.ingest_task_name == "custom.ingest.run"
    assert config.graphrag_index_task_name == "custom.graphrag.index"
    assert config.graphrag_partition_rebuild_task_name == "custom.graphrag.rebuild"


@pytest.mark.parametrize(
    "name",
    [
        "INGEST_TASK_NAME",
        "GRAPHRAG_INDEX_TASK_NAME",
        "GRAPHRAG_PARTITION_REBUILD_TASK_NAME",
    ],
)
def test_worker_rejects_blank_task_names(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.setenv(name, "  ")

    with pytest.raises(ValueError, match=f"{name} must not be empty"):
        WorkerConfig.from_env()


def test_worker_rejects_the_reserved_celery_task_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INGEST_TASK_NAME", "celery.chain")

    with pytest.raises(ValueError, match="reserved task namespace"):
        WorkerConfig.from_env()


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "INGEST_TASK_NAME": "custom.same",
            "GRAPHRAG_INDEX_TASK_NAME": "custom.same",
        },
        {
            "INGEST_TASK_NAME": "apps.ingestion.tasks.index_document_graphrag",
        },
        {
            "GRAPHRAG_INDEX_TASK_NAME": (
                "apps.ingestion.tasks.reextract_document_metadata"
            ),
        },
    ],
)
def test_worker_rejects_task_name_collisions(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str],
) -> None:
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="document pipeline task name collision"):
        WorkerConfig.from_env()
