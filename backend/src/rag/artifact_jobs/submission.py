"""Immutable input contract for artifact-job submission."""

from pydantic import ConfigDict, Field

from rag.shared.contracts.http import ContractModel


class ArtifactJobSubmission(ContractModel):
    model_config = ConfigDict(frozen=True)

    original_request: str = Field(..., min_length=1)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=120)
    group_path: str | None = Field(default=None, min_length=1)
    document_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
