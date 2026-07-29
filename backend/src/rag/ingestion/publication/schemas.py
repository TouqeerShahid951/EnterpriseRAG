"""Worker-facing contracts for index generation publication."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from rag.abbreviations.schemas import AbbreviationImportEntry
from rag.documents.internal_schemas import ClaimRecord
from rag.shared.contracts.http import ContractModel


class IndexGenerationStageRequest(ContractModel):
    generation_id: str = Field(..., min_length=36, max_length=36)
    run_token: str = Field(..., min_length=1, max_length=100)
    input_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    configuration_digest: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    expected_point_count: int = Field(..., ge=0)
    expected_item_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    vector_dimension: int = Field(..., ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    claims: list[ClaimRecord] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    abbreviation_entries: list[AbbreviationImportEntry] = Field(default_factory=list)


class IndexGenerationTransitionRequest(ContractModel):
    generation_id: str = Field(..., min_length=36, max_length=36)
    run_token: str = Field(..., min_length=1, max_length=100)


class IndexGenerationResponse(ContractModel):
    generation_id: str
    state: Literal["building", "verified", "active", "retiring", "retired", "failed"]
    expected_point_count: int
    expected_item_hash: str
    vector_dimension: int


class IndexGenerationCancelResponse(ContractModel):
    generation_id: str | None = None
