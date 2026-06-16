from datetime import datetime

from pydantic import Field

from ..shared.contracts.reranker_models import DEFAULT_RERANKER_MODEL
from .common import ContractModel


class RagConfigRequest(ContractModel):
    provider: str = "ollama"
    host: str = Field(..., min_length=1)
    port: int = Field(default=11434, ge=1, le=65535)
    embedding_host: str | None = None
    embedding_port: int | None = Field(default=None, ge=1, le=65535)
    reasoning_host: str | None = None
    reasoning_port: int | None = Field(default=None, ge=1, le=65535)
    routing_host: str | None = None
    routing_port: int | None = Field(default=None, ge=1, le=65535)
    faithfulness_host: str | None = None
    faithfulness_port: int | None = Field(default=None, ge=1, le=65535)
    ingestion_host: str | None = None
    ingestion_port: int | None = Field(default=None, ge=1, le=65535)
    chat_model: str = Field(..., min_length=1)
    embed_model: str = Field(..., min_length=1)
    reasoning_model: str | None = None
    routing_model: str | None = None
    faithfulness_model: str | None = None
    ingestion_model: str | None = None
    vision_model: str | None = None
    thinking_enabled: bool = False
    json_num_predict: int = Field(default=4096, ge=256, le=32768)
    retrieval_token_budget: int = Field(default=12000, ge=1000, le=200000)
    reranker_model: str = Field(default=DEFAULT_RERANKER_MODEL, min_length=1)
    chat_timeout_seconds: float = Field(default=180.0, gt=0)
    embed_timeout_seconds: float = Field(default=45.0, gt=0)


class RagModelDiscoveryRequest(ContractModel):
    provider: str = "ollama"
    host: str = Field(..., min_length=1)
    port: int = Field(default=11434, ge=1, le=65535)
    embedding_host: str | None = None
    embedding_port: int | None = Field(default=None, ge=1, le=65535)
    reasoning_host: str | None = None
    reasoning_port: int | None = Field(default=None, ge=1, le=65535)
    routing_host: str | None = None
    routing_port: int | None = Field(default=None, ge=1, le=65535)
    faithfulness_host: str | None = None
    faithfulness_port: int | None = Field(default=None, ge=1, le=65535)
    ingestion_host: str | None = None
    ingestion_port: int | None = Field(default=None, ge=1, le=65535)
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)


class RagConfigHealth(ContractModel):
    status: str
    message: str
    embedding_dimension: int | None = None
    chat_latency_ms: int | None = None
    embed_latency_ms: int | None = None
    checked_at: datetime | None = None


class RerankerModelOption(ContractModel):
    model: str
    default: bool = False


class RerankerModelsResponse(ContractModel):
    models: list[RerankerModelOption] = Field(default_factory=list)


class RagConfigResponse(ContractModel):
    source: str
    provider: str
    base_url: str
    host: str
    port: int
    embedding_base_url: str
    embedding_host: str
    embedding_port: int
    reasoning_base_url: str | None = None
    reasoning_host: str | None = None
    reasoning_port: int | None = None
    routing_base_url: str | None = None
    routing_host: str | None = None
    routing_port: int | None = None
    faithfulness_base_url: str | None = None
    faithfulness_host: str | None = None
    faithfulness_port: int | None = None
    ingestion_base_url: str | None = None
    ingestion_host: str | None = None
    ingestion_port: int | None = None
    chat_model: str
    embed_model: str
    reasoning_model: str | None = None
    routing_model: str | None = None
    faithfulness_model: str | None = None
    ingestion_model: str | None = None
    vision_model: str | None = None
    thinking_enabled: bool
    json_num_predict: int
    retrieval_token_budget: int
    reranker_model: str
    chat_timeout_seconds: float
    embed_timeout_seconds: float
    health: RagConfigHealth


class RagConfigTestResponse(ContractModel):
    provider: str
    base_url: str
    embedding_base_url: str
    reasoning_base_url: str | None = None
    routing_base_url: str | None = None
    faithfulness_base_url: str | None = None
    ingestion_base_url: str | None = None
    chat_models: list[str] = Field(default_factory=list)
    embedding_models: list[str] = Field(default_factory=list)
    reasoning_models: list[str] = Field(default_factory=list)
    routing_models: list[str] = Field(default_factory=list)
    faithfulness_models: list[str] = Field(default_factory=list)
    ingestion_models: list[str] = Field(default_factory=list)
    vision_models: list[str] = Field(default_factory=list)
    available_models: list[str] = Field(default_factory=list)
    thinking_enabled: bool
    json_num_predict: int
    retrieval_token_budget: int
    reranker_model: str
    health: RagConfigHealth


class VllmServiceDeploymentLimits(ContractModel):
    max_model_len: int = Field(..., ge=256, le=262144)
    gpu_memory_utilization: float = Field(..., gt=0.0, le=1.0)
    max_num_seqs: int = Field(..., ge=1, le=1024)
    max_num_batched_tokens: int = Field(..., ge=256, le=262144)
    kv_cache_memory_bytes: str | None = Field(default=None, min_length=1, max_length=32)


class VllmDeploymentConfigRequest(ContractModel):
    text: VllmServiceDeploymentLimits
    embeddings: VllmServiceDeploymentLimits
    vision: VllmServiceDeploymentLimits


class VllmDeploymentConfigResponse(ContractModel):
    source: str = "environment"
    apply_status: str = "restart_required"
    message: str | None = None
    text: VllmServiceDeploymentLimits
    embeddings: VllmServiceDeploymentLimits
    vision: VllmServiceDeploymentLimits


class RagModelDiscoveryResponse(ContractModel):
    provider: str
    base_url: str
    embedding_base_url: str
    reasoning_base_url: str | None = None
    routing_base_url: str | None = None
    faithfulness_base_url: str | None = None
    ingestion_base_url: str | None = None
    chat_models: list[str] = Field(default_factory=list)
    embedding_models: list[str] = Field(default_factory=list)
    reasoning_models: list[str] = Field(default_factory=list)
    routing_models: list[str] = Field(default_factory=list)
    faithfulness_models: list[str] = Field(default_factory=list)
    ingestion_models: list[str] = Field(default_factory=list)
    vision_models: list[str] = Field(default_factory=list)
    available_models: list[str] = Field(default_factory=list)
