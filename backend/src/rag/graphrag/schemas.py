"""Public GraphRAG HTTP contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from rag.shared.contracts.http import ContractModel


class GraphRAGWorkerState(ContractModel):
    name: str
    pool_size: int = Field(..., ge=0)
    active_jobs: int = Field(..., ge=0)


class GraphRAGActiveTask(ContractModel):
    task_id: str
    task_name: str
    worker: str
    job_id: str | None = None
    document_id: str | None = None
    started_at: datetime | None = None
    elapsed_seconds: int | None = None


class GraphRAGQueuedTask(ContractModel):
    task_id: str
    task_name: str
    job_id: str | None = None
    document_id: str | None = None


class GraphRAGStatusResponse(ContractModel):
    enabled: bool
    queue_name: str
    queued_jobs: int | None = None
    queue_error: str | None = None
    worker_online: bool = False
    worker_error: str | None = None
    active_jobs: int = 0
    observed_pool_size: int = 0
    workers: list[GraphRAGWorkerState] = Field(default_factory=list)
    active_tasks: list[GraphRAGActiveTask] = Field(default_factory=list)
    queued_tasks: list[GraphRAGQueuedTask] = Field(default_factory=list)


class GraphRAGCancelRequest(ContractModel):
    task_id: str = Field(..., min_length=1, max_length=200)


class GraphRAGCancelResponse(ContractModel):
    task_id: str
    job_id: str
    document_id: str
    status: Literal["cancelled"] = "cancelled"
    message: str


class DocumentGraphEnrichmentResponse(ContractModel):
    document_id: str
    job_id: str
    status: Literal["queued"] = "queued"
    message: str = "Graph enrichment queued."
