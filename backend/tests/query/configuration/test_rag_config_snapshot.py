from __future__ import annotations

from copy import deepcopy

import pytest

from rag.core.config import Settings
from rag.query.configuration.mapping import (
    rag_config_from_snapshot,
    rag_config_response,
)
from rag.query.configuration.models import RagConfigRecord
from rag.query.service import LocalRagService


def test_resolved_mixed_provider_snapshot_round_trips_runtime_fields() -> None:
    original = _record()
    snapshot = rag_config_response(original).model_dump(mode="json")

    restored = rag_config_from_snapshot(snapshot)

    assert restored.source == original.source
    assert restored.provider == original.provider
    assert restored.embedding_provider == original.embedding_provider
    assert restored.effective_reasoning_provider == original.effective_reasoning_provider
    assert restored.effective_routing_provider == original.effective_routing_provider
    assert restored.effective_faithfulness_provider == original.effective_faithfulness_provider
    assert restored.effective_ingestion_provider == original.effective_ingestion_provider
    assert restored.effective_vision_provider == original.effective_vision_provider
    assert restored.effective_reasoning_base_url == original.effective_reasoning_base_url
    assert restored.effective_routing_base_url == original.effective_routing_base_url
    assert restored.chat_model == original.chat_model
    assert restored.embed_model == original.embed_model
    assert restored.reranker_model == original.reranker_model
    assert restored.retrieval_token_budget == original.retrieval_token_budget
    assert restored.query_planner_enabled is original.query_planner_enabled
    assert restored.embedding_port == 0


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("provider",), "unsupported"),
        (("embedding_provider",), "unsupported"),
        (("reranker_model",), "unsupported/model"),
        (("chat_model",), " "),
        (("embed_model",), ""),
        (("base_url",), ""),
        (("chat_timeout_seconds",), 0),
        (("embed_timeout_seconds",), -1),
        (("json_num_predict",), 128),
        (("retrieval_token_budget",), 999),
    ],
)
def test_invalid_snapshot_values_fail_closed(
    path: tuple[str, ...], value: object
) -> None:
    snapshot = _snapshot()
    target = snapshot
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment,index]
    target[path[-1]] = value

    with pytest.raises(ValueError):
        rag_config_from_snapshot(snapshot)


def test_empty_missing_and_extra_snapshot_fields_fail_closed() -> None:
    with pytest.raises(ValueError):
        rag_config_from_snapshot({})

    missing = _snapshot()
    missing.pop("chat_model")
    with pytest.raises(ValueError):
        rag_config_from_snapshot(missing)

    extra = _snapshot()
    extra["live_fallback"] = True
    with pytest.raises(ValueError):
        rag_config_from_snapshot(extra)


def test_explicit_runtime_config_bypasses_live_repository_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = rag_config_from_snapshot(_snapshot())

    def unexpected_live_lookup(**_kwargs: object) -> RagConfigRecord:
        raise AssertionError("live RAG config must not be read")

    monkeypatch.setattr(
        "rag.query.service.effective_rag_config", unexpected_live_lookup
    )
    service = LocalRagService(
        config=Settings(document_repository="memory"),
        rag_config=record,
        ollama=object(),  # type: ignore[arg-type]
        qdrant=object(),  # type: ignore[arg-type]
        session_store=object(),  # type: ignore[arg-type]
        conflict_checker=object(),  # type: ignore[arg-type]
        artifact_service=object(),  # type: ignore[arg-type]
        artifact_job_service=object(),  # type: ignore[arg-type]
    )

    assert service.rag_config is record
    assert service.nodes.reasoning_model == record.effective_reasoning_model
    assert service.nodes.routing_model == record.routing_model
    assert service.nodes.faithfulness_model == record.faithfulness_model
    assert service.nodes.reranker_model == record.reranker_model
    assert service.nodes.query_planner_enabled is record.query_planner_enabled


def _snapshot() -> dict[str, object]:
    return deepcopy(rag_config_response(_record()).model_dump(mode="json"))


def _record() -> RagConfigRecord:
    return RagConfigRecord(
        source="workspace",
        provider="vllm",
        embedding_provider="fastembed",
        reasoning_provider="vllm",
        routing_provider="ollama",
        faithfulness_provider="ollama",
        ingestion_provider="vllm",
        vision_provider="ollama",
        base_url="http://vllm-chat:8000",
        embedding_base_url="http://local-fastembed:8000",
        reasoning_base_url="http://vllm-reasoning:8000",
        routing_base_url="http://ollama-routing:11434",
        faithfulness_base_url="http://ollama-faithfulness:11434",
        ingestion_base_url="http://vllm-ingestion:8000",
        vision_base_url="http://ollama-vision:11434",
        chat_model="Qwen/Qwen3-14B-AWQ",
        embed_model="nomic-ai/nomic-embed-text-v1.5-Q",
        reasoning_model="Qwen/Qwen3-14B-AWQ",
        routing_model="qwen3:8b",
        faithfulness_model="qwen3:14b",
        ingestion_model="Qwen/Qwen3-14B-AWQ",
        vision_model="qwen2.5vl:3b",
        thinking_enabled=True,
        json_num_predict=8192,
        retrieval_token_budget=24000,
        query_planner_enabled=False,
        reranker_model="jinaai/jina-reranker-v1-turbo-en",
        chat_timeout_seconds=180,
        embed_timeout_seconds=45,
        health_status="ok",
        health_message="Snapshot source was healthy.",
        embedding_dimension=768,
        chat_latency_ms=15,
        embed_latency_ms=8,
    )
