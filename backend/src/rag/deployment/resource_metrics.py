"""Read-only resource snapshot contract for the API runtime."""

from datetime import datetime
from typing import Protocol

from pydantic import Field

from rag.shared.contracts.http import ContractModel


class ResourceMetric(ContractModel):
    label: str
    scope: str
    percent: float | None = Field(None, ge=0, le=100)
    used_bytes: int | None = Field(None, ge=0)
    total_bytes: int | None = Field(None, gt=0)
    unavailable_reason: str | None = None


class GpuDevice(ContractModel):
    id: str
    name: str
    utilization_percent: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    memory_used_bytes: int | None = Field(None, ge=0)
    memory_total_bytes: int | None = Field(None, gt=0)
    temperature_c: float | None = Field(None, ge=0, allow_inf_nan=False)
    power_watts: float | None = Field(None, ge=0, allow_inf_nan=False)


class GpuSnapshot(ContractModel):
    devices: list[GpuDevice] = Field(default_factory=list)
    scope: str = "GPUs visible to the API container · includes other workloads, excludes remote model servers"
    unavailable_reason: str | None = None


class ResourceSnapshot(ContractModel):
    sampled_at: datetime
    metrics: list[ResourceMetric]
    gpu: GpuSnapshot = Field(default_factory=GpuSnapshot)


class ResourceReader(Protocol):
    def read(self) -> ResourceSnapshot: ...
