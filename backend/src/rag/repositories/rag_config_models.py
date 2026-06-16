"""Workspace RAG configuration records and repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

from rag.shared.contracts.reranker_models import DEFAULT_RERANKER_MODEL, normalize_reranker_model

ACTIVE_CONFIG_KEY = "active"
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_VLLM_PORT = 8000
SUPPORTED_INFERENCE_PROVIDERS = {"ollama", "vllm"}


@dataclass(frozen=True)
class RagConfigRecord:
    base_url: str
    chat_model: str
    embed_model: str
    faithfulness_model: str | None
    chat_timeout_seconds: float
    embed_timeout_seconds: float
    embedding_base_url: str = ""
    reasoning_base_url: str | None = None
    routing_base_url: str | None = None
    faithfulness_base_url: str | None = None
    ingestion_base_url: str | None = None
    thinking_enabled: bool = False
    reasoning_model: str | None = None
    routing_model: str | None = None
    ingestion_model: str | None = None
    vision_model: str | None = None
    json_num_predict: int = 4096
    retrieval_token_budget: int = 12000
    reranker_model: str = DEFAULT_RERANKER_MODEL
    health_status: str = "unknown"
    health_message: str = "Not checked."
    embedding_dimension: int | None = None
    chat_latency_ms: int | None = None
    embed_latency_ms: int | None = None
    last_checked_at: datetime | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None
    source: str = "workspace"
    provider: str = "ollama"

    def __post_init__(self) -> None:
        if not self.embedding_base_url:
            object.__setattr__(self, "embedding_base_url", self.base_url)
        object.__setattr__(self, "reranker_model", normalize_reranker_model(self.reranker_model))
        for field_name in ("reasoning_base_url", "routing_base_url", "faithfulness_base_url", "ingestion_base_url"):
            if not getattr(self, field_name):
                object.__setattr__(self, field_name, self.base_url)

    @property
    def effective_reasoning_model(self) -> str | None:
        return self.reasoning_model or self.routing_model

    @property
    def effective_reasoning_base_url(self) -> str:
        return self.reasoning_base_url or self.base_url

    @property
    def effective_routing_base_url(self) -> str:
        return self.routing_base_url or self.effective_reasoning_base_url

    @property
    def effective_faithfulness_base_url(self) -> str:
        return self.faithfulness_base_url or self.base_url

    @property
    def effective_ingestion_base_url(self) -> str:
        return self.ingestion_base_url or self.base_url

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or self.base_url

    @property
    def port(self) -> int:
        parsed = urlsplit(self.base_url)
        return parsed.port or (DEFAULT_VLLM_PORT if self.provider == "vllm" else DEFAULT_OLLAMA_PORT)

    @property
    def embedding_host(self) -> str:
        return urlsplit(self.embedding_base_url).hostname or self.embedding_base_url

    @property
    def embedding_port(self) -> int:
        parsed = urlsplit(self.embedding_base_url)
        return parsed.port or (DEFAULT_VLLM_PORT if self.provider == "vllm" else DEFAULT_OLLAMA_PORT)

    def role_host(self, role: str) -> str:
        base_url = self._role_base_url(role)
        return urlsplit(base_url).hostname or base_url

    def role_port(self, role: str) -> int:
        parsed = urlsplit(self._role_base_url(role))
        return parsed.port or (DEFAULT_VLLM_PORT if self.provider == "vllm" else DEFAULT_OLLAMA_PORT)

    def _role_base_url(self, role: str) -> str:
        return {
            "reasoning": self.effective_reasoning_base_url,
            "routing": self.effective_routing_base_url,
            "faithfulness": self.effective_faithfulness_base_url,
            "ingestion": self.effective_ingestion_base_url,
        }[role]


class RagConfigRepository(Protocol):
    def get_active(self) -> RagConfigRecord | None: ...
    def save_active(self, config: RagConfigRecord) -> RagConfigRecord: ...
