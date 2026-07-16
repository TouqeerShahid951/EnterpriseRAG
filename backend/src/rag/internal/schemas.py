"""Shared worker-facing internal HTTP contracts."""

from typing import Literal

from pydantic import Field

from rag.shared.contracts.http import ContractModel


class ServiceTokenContext(ContractModel):
    service_name: str
    scopes: tuple[str, ...] = Field(default_factory=tuple)


class InternalMutationResponse(ContractModel):
    status: Literal["accepted"] = "accepted"
