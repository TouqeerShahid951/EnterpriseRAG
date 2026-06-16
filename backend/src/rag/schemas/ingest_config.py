from datetime import datetime

from pydantic import Field

from .common import ContractModel


class IngestConfigRequest(ContractModel):
    worker_concurrency: int = Field(..., ge=1, le=10)


class IngestWorkerState(ContractModel):
    name: str
    pool_size: int = Field(..., ge=0)
    active_jobs: int = Field(..., ge=0)


class IngestConfigResponse(ContractModel):
    worker_concurrency: int
    recommended_concurrency: int = 1
    worker_online: bool
    active_jobs: int
    observed_pool_size: int
    apply_status: str
    workers: list[IngestWorkerState] = Field(default_factory=list)
    hazardous: bool = False
    updated_at: datetime | None = None
