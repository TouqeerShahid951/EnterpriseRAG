from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(ContractModel):
    code: str
    message: str
    field: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(ContractModel):
    error: ErrorDetail


class StubResponse(ContractModel):
    status: Literal["not_implemented"] = "not_implemented"
    detail: str = "Route contract is reserved for Milestone 0."


class HealthResponse(ContractModel):
    status: Literal["ok", "unavailable", "scaffold"]
    ready: bool
    detail: str | None = None
