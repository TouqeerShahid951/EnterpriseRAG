"""Document ownership and sharing HTTP contracts."""

from typing import Literal

from pydantic import Field

from rag.shared.contracts.http import ContractModel


class DocumentSharesUpdateRequest(ContractModel):
    group_paths: list[str] = Field(default_factory=list, max_length=128)


class DocumentOwnerUpdateRequest(ContractModel):
    group_path: str = Field(..., min_length=1)


class DocumentUnshareRequest(ContractModel):
    group_path: str = Field(..., min_length=1)


class DocumentSharesResponse(ContractModel):
    document_id: str
    owner_group_path: str
    shared_group_paths: list[str] = Field(default_factory=list)
    access_group_paths: list[str] = Field(default_factory=list)
    governance_owner: Literal["space", "system"] = "space"
