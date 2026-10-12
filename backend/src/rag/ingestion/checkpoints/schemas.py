"""Worker-facing checkpoint wire schemas."""

from __future__ import annotations

from pydantic import Field

from rag.shared.contracts.http import ContractModel


class CheckpointCommitRequest(ContractModel):
    run_token: str = Field(..., min_length=1, max_length=100)
    document_id: str
    stage_key: str = Field(..., min_length=1, max_length=200)
    object_key: str = Field(..., min_length=1, max_length=500)
    schema_version: int = Field(..., ge=1)
    body_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    compressed_size: int = Field(..., gt=0, le=64 * 1024 * 1024)
    decoded_size: int = Field(..., gt=0, le=256 * 1024 * 1024)
    upstream_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    range_start: int | None = Field(default=None, ge=0)
    range_end: int | None = Field(default=None, gt=0)
    model_identity: str | None = Field(default=None, max_length=300)
    vector_dimension: int | None = Field(default=None, gt=0)


class CheckpointResponse(ContractModel):
    job_id: str
    document_id: str
    stage_key: str
    object_key: str
    schema_version: int
    body_sha256: str
    compressed_size: int
    decoded_size: int
    upstream_sha256: str
    configuration_digest: str
    range_start: int | None = None
    range_end: int | None = None
    model_identity: str | None = None
    vector_dimension: int | None = None


class CheckpointListResponse(ContractModel):
    checkpoints: list[CheckpointResponse] = Field(default_factory=list)
