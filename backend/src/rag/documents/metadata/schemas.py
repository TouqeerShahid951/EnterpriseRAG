"""Document metadata and supersession HTTP contracts."""

from pydantic import Field

from rag.shared.contracts.clearance import ClearanceLevel
from rag.shared.contracts.http import ContractModel


class DocumentClearanceUpdateRequest(ContractModel):
    clearance_level: ClearanceLevel


class DocumentTopicsUpdateRequest(ContractModel):
    topics: list[str] = Field(default_factory=list, max_length=32)
    llm_topics: list[str] = Field(default_factory=list, max_length=32)


class SupersedeRequest(ContractModel):
    supersedes: list[str] = Field(default_factory=list)


class VersionNode(ContractModel):
    id: str
    effective_date: str | None = None
    is_current: bool
    superseded_by: str | None = None


class VersionChainResponse(ContractModel):
    document_id: str
    chain: list[VersionNode] = Field(default_factory=list)
