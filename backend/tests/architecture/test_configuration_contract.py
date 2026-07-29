"""Static contract checks for configuration ownership across runtime layers."""

from __future__ import annotations

import re
from pathlib import Path

from rag.core.config import Settings
from rag.ingestion.config import WorkerConfig
from rag.ingestion.configuration.schemas import (
    IngestConfigRequest,
    IngestConfigResponse,
    IngestRuntimeConfigResponse,
)
from rag.shared.contracts.rag_defaults import (
    DEFAULT_EVIDENCE_GATE_POLICY,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_FAITHFULNESS_POLICY,
    DEFAULT_FAITHFULNESS_TIMEOUT_SECONDS,
    DEFAULT_RAG_HTTP_TIMEOUT_SECONDS,
    DEFAULT_RERANKER_DEVICE,
    DEFAULT_ROUTING_TIMEOUT_SECONDS,
    DEFAULT_REASONING_TIMEOUT_SECONDS,
    DEFAULT_VLLM_CHAT_MODEL,
    DEFAULT_VLLM_VISION_MODEL_ID,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
COMPOSE_PATH = REPOSITORY_ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = REPOSITORY_ROOT / ".env.example"

TOPOLOGY_RAG_KEYS = frozenset(
    {
        "EMBEDDINGS_BASE_URL",
        "OLLAMA_BASE_URL",
        "RAG_DENSE_CACHE_DIR",
        "RAG_RERANKER_CACHE_DIR",
        "RAG_SPARSE_CACHE_DIR",
    }
)
LEGACY_ENV_KEYS = frozenset({"RAG_CHUNK_MAX_CHARS", "RAG_CHUNK_OVERLAP_CHARS"})
RETIRED_ROUTER_ENV_KEYS = frozenset(
    {
        "RAG_INTENT_ROUTER_VERSION",
        "RAG_ROUTE_LLM_VERIFIER_ENABLED",
        "RAG_ROUTE_LLM_VERIFIER_MODEL",
        "RAG_SOURCE_ROUTER_LLM_ENABLED",
        "RAG_SOURCE_ROUTER_LLM_MIN_CONFIDENCE",
    }
)
RETIRED_FAITHFULNESS_ENV_KEYS = frozenset(
    {"RAG_DEFER_FAITHFULNESS", "RAG_FAITHFULNESS_THRESHOLD"}
)
FORBIDDEN_DOCKERFILE_DEFAULTS = frozenset(
    {
        "ENABLE_MOCK_MODELS",
        "OLLAMA_BASE_URL",
        "OLLAMA_CHAT_MODEL",
        "OLLAMA_EMBED_MODEL",
        "RAG_EMBEDDING_PROVIDER",
        "RAG_FASTEMBED_MODEL",
        "RAG_MODEL_PROVIDER",
        "RAG_RERANKER_MODEL",
        "RAG_SPARSE_MODEL",
        "VLLM_CHAT_MODEL",
        "VLLM_VISION_MODEL_ID",
    }
)


def test_python_defaults_preserve_the_supported_docker_profile() -> None:
    config = Settings()

    assert config.rag_http_timeout_seconds == DEFAULT_RAG_HTTP_TIMEOUT_SECONDS == 180.0
    assert (
        config.rag_routing_timeout_seconds
        == DEFAULT_ROUTING_TIMEOUT_SECONDS
        == 5.0
    )
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
    assert config.rag_evidence_gate_policy == DEFAULT_EVIDENCE_GATE_POLICY == "adaptive"
    assert config.rag_faithfulness_policy == DEFAULT_FAITHFULNESS_POLICY == "adaptive"
    assert config.rag_reranker_device == DEFAULT_RERANKER_DEVICE == "auto"
    assert config.graphrag_enabled is True
    assert config.embedding_model_id == DEFAULT_EMBEDDING_MODEL_ID == "nomic-ai/nomic-embed-text-v1.5"
    assert config.vllm_chat_model == DEFAULT_VLLM_CHAT_MODEL == "Qwen/Qwen3-8B-AWQ"
    assert config.vllm_vision_model_id == DEFAULT_VLLM_VISION_MODEL_ID == "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"


def test_compose_exposes_every_typed_rag_override() -> None:
    backend_environment = _compose_backend_environment()
    settings_keys = {
        name.upper()
        for name in Settings.model_fields
        if name.startswith(("rag_", "graphrag_", "ollama_", "vllm_"))
        or name in {"embedding_model_id", "embeddings_base_url"}
    }

    assert settings_keys <= backend_environment.keys()


def test_retired_router_environment_is_not_exposed() -> None:
    assert RETIRED_ROUTER_ENV_KEYS.isdisjoint(_compose_backend_environment())
    assert RETIRED_ROUTER_ENV_KEYS.isdisjoint(
        re.findall(
            r"^([A-Z][A-Z0-9_]*)=",
            ENV_EXAMPLE_PATH.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )


def test_retired_faithfulness_environment_is_not_exposed() -> None:
    assert RETIRED_FAITHFULNESS_ENV_KEYS.isdisjoint(_compose_backend_environment())
    assert RETIRED_FAITHFULNESS_ENV_KEYS.isdisjoint(
        re.findall(
            r"^([A-Z][A-Z0-9_]*)=",
            ENV_EXAMPLE_PATH.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )


def test_ingestion_quality_preset_is_not_runtime_configuration() -> None:
    assert "ingestion_quality_preset" not in Settings.model_fields
    assert "ingestion_quality_preset" not in WorkerConfig.__dataclass_fields__
    assert all(
        "quality_preset" not in schema.model_fields
        for schema in (IngestConfigRequest, IngestConfigResponse, IngestRuntimeConfigResponse)
    )
    assert "INGESTION_QUALITY_PRESET" not in COMPOSE_PATH.read_text(encoding="utf-8")
    assert "INGESTION_QUALITY_PRESET=" not in ENV_EXAMPLE_PATH.read_text(encoding="utf-8")


def test_compose_does_not_own_behavioral_rag_defaults() -> None:
    backend_environment = _compose_backend_environment()
    behavioral_entries = {
        key: value
        for key, value in backend_environment.items()
        if key.startswith(("RAG_", "GRAPHRAG_", "OLLAMA_"))
        or key
        in {
            "EMBEDDING_MODEL_ID",
            "ENABLE_MOCK_MODELS",
            "VLLM_CHAT_MODEL",
            "VLLM_VISION_MODEL_ID",
        }
    }

    duplicated_defaults = {
        key: value
        for key, value in behavioral_entries.items()
        if key not in TOPOLOGY_RAG_KEYS and value is not None
    }
    assert duplicated_defaults == {}


def test_env_example_documents_every_optional_compose_passthrough() -> None:
    compose_passthrough = {
        match.group(1)
        for match in re.finditer(
            r"^\s+([A-Z][A-Z0-9_]*):\s*$",
            COMPOSE_PATH.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    }
    documented = {
        match.group(1)
        for match in re.finditer(
            r"^([A-Z][A-Z0-9_]*)=",
            ENV_EXAMPLE_PATH.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    }

    assert compose_passthrough - LEGACY_ENV_KEYS <= documented


def test_dockerfiles_do_not_define_mutable_rag_defaults() -> None:
    dockerfiles = (
        BACKEND_ROOT / "apps" / "api" / "Dockerfile",
        BACKEND_ROOT / "apps" / "workers" / "document_pipeline" / "Dockerfile",
    )

    assigned: set[str] = set()
    for path in dockerfiles:
        assigned.update(
            re.findall(
                r"^\s*(?:ENV\s+)?([A-Z][A-Z0-9_]*)=",
                path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            )
        )

    assert assigned.isdisjoint(FORBIDDEN_DOCKERFILE_DEFAULTS)


def _compose_backend_environment() -> dict[str, str | None]:
    source = COMPOSE_PATH.read_text(encoding="utf-8")
    start = source.index("x-backend-env: &backend-env")
    end = source.index("\nx-fastembed-cache-volume:", start)
    entries: dict[str, str | None] = {}
    for line in source[start:end].splitlines()[1:]:
        match = re.fullmatch(r"  ([A-Z][A-Z0-9_]*):(?:\s+(.*))?", line)
        if match:
            entries[match.group(1)] = match.group(2)
    return entries
