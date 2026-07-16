"""Public vLLM deployment configuration contracts."""

from typing import Literal

from pydantic import Field

from rag.shared.contracts.http import ContractModel


class VllmServiceDeploymentLimits(ContractModel):
    max_model_len: int = Field(..., ge=256, le=262144)
    gpu_memory_utilization: float = Field(..., gt=0.0, le=1.0)
    max_num_seqs: int = Field(..., ge=1, le=1024)
    max_num_batched_tokens: int = Field(..., ge=256, le=262144)
    kv_cache_memory_bytes: str | None = Field(
        default=None, min_length=1, max_length=32
    )


VllmDeploymentService = Literal["text", "embeddings", "vision"]


class VllmDeploymentConfigRequest(ContractModel):
    text: VllmServiceDeploymentLimits
    embeddings: VllmServiceDeploymentLimits
    vision: VllmServiceDeploymentLimits
    services: list[VllmDeploymentService] | None = Field(
        default=None, min_length=1, max_length=3
    )


class VllmDeploymentConfigResponse(ContractModel):
    source: str = "environment"
    apply_status: str = "restart_required"
    message: str | None = None
    text: VllmServiceDeploymentLimits
    embeddings: VllmServiceDeploymentLimits
    vision: VllmServiceDeploymentLimits
