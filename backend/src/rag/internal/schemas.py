"""Shared worker-facing internal HTTP contracts."""

from typing import Literal

from rag.shared.contracts.http import ContractModel


class InternalMutationResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
