"""Document lifecycle HTTP contracts."""

from typing import Literal

from rag.shared.contracts.http import ContractModel


class DeleteDocumentResponse(ContractModel):
    id: str
    status: Literal["soft_deleted", "permanently_deleted"] = "soft_deleted"
