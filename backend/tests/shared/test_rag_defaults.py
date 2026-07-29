from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag.core.config import Settings
from rag.shared.contracts.rag_defaults import (
    DEFAULT_EVIDENCE_GATE_POLICY,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_FAITHFULNESS_MODEL,
    DEFAULT_FAITHFULNESS_POLICY,
    DEFAULT_FAITHFULNESS_TIMEOUT_SECONDS,
    DEFAULT_GRAPHRAG_ENABLED,
    DEFAULT_RAG_HTTP_TIMEOUT_SECONDS,
    DEFAULT_RERANKER_DEVICE,
    DEFAULT_RERANKER_MAX_CANDIDATES,
    DEFAULT_RERANKER_TIMEOUT_SECONDS,
    DEFAULT_REASONING_MODEL,
    DEFAULT_REASONING_TIMEOUT_SECONDS,
    DEFAULT_ROUTING_MODEL,
    DEFAULT_VLLM_CHAT_MODEL,
    DEFAULT_VLLM_VISION_MODEL_ID,
)


def test_settings_use_canonical_docker_resolved_rag_defaults() -> None:
    config = Settings()

    assert config.graphrag_enabled is DEFAULT_GRAPHRAG_ENABLED is True
    assert config.rag_http_timeout_seconds == DEFAULT_RAG_HTTP_TIMEOUT_SECONDS == 180.0
    assert config.rag_evidence_gate_policy == DEFAULT_EVIDENCE_GATE_POLICY == "adaptive"
    assert config.rag_faithfulness_policy == DEFAULT_FAITHFULNESS_POLICY == "adaptive"
    assert config.vllm_chat_model == DEFAULT_VLLM_CHAT_MODEL == "Qwen/Qwen3-8B-AWQ"
    assert config.vllm_vision_model_id == DEFAULT_VLLM_VISION_MODEL_ID
    assert config.embedding_model_id == DEFAULT_EMBEDDING_MODEL_ID
    assert config.rag_reasoning_model == DEFAULT_REASONING_MODEL
    assert config.rag_faithfulness_model == DEFAULT_FAITHFULNESS_MODEL
    assert config.rag_routing_model == DEFAULT_ROUTING_MODEL
    assert (
        config.rag_reasoning_timeout_seconds
        == DEFAULT_REASONING_TIMEOUT_SECONDS
        == 30.0
    )
    assert (
        config.rag_faithfulness_timeout_seconds
        == DEFAULT_FAITHFULNESS_TIMEOUT_SECONDS
        == 30.0
    )
    assert config.rag_reranker_device == DEFAULT_RERANKER_DEVICE == "auto"
    assert (
        config.rag_reranker_max_candidates
        == DEFAULT_RERANKER_MAX_CANDIDATES
        == 24
    )
    assert (
        config.rag_reranker_timeout_seconds
        == DEFAULT_RERANKER_TIMEOUT_SECONDS
        == 30.0
    )


def test_settings_normalize_provider_case_and_empty_role_override() -> None:
    config = Settings(rag_model_provider="VLLM", rag_chat_provider="  ")  # type: ignore[arg-type]

    assert config.rag_model_provider == "vllm"
    assert config.rag_chat_provider is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rag_model_provider", "unsupported"),
        ("rag_embedding_provider", "unsupported"),
        ("rag_http_timeout_seconds", 0),
        ("rag_reasoning_timeout_seconds", 0),
        ("rag_faithfulness_timeout_seconds", 301),
        ("rag_reranker_timeout_seconds", 0),
        ("rag_top_k", 0),
        ("rag_evidence_gate_policy", "sometimes"),
        ("rag_faithfulness_policy", "sometimes"),
        ("rag_reranker_device", "metal"),
    ],
)
def test_settings_reject_invalid_rag_environment_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
