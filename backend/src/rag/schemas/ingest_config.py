from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import ContractModel

IngestionQualityPreset = Literal["fast", "balanced", "high_accuracy"]


class IngestConfigRequest(ContractModel):
    worker_concurrency: int = Field(..., ge=1, le=10)
    quality_preset: IngestionQualityPreset = "fast"
    ocr_review_confidence_threshold: float = Field(..., ge=0.0, le=1.0)
    vision_layout_repair_enabled: bool = False


class IngestWorkerState(ContractModel):
    name: str
    pool_size: int = Field(..., ge=0)
    active_jobs: int = Field(..., ge=0)


class IngestConfigResponse(ContractModel):
    worker_concurrency: int
    quality_preset: IngestionQualityPreset
    ocr_review_confidence_threshold: float
    vision_layout_repair_enabled: bool
    recommended_concurrency: int = 1
    worker_online: bool
    active_jobs: int
    observed_pool_size: int
    apply_status: str
    workers: list[IngestWorkerState] = Field(default_factory=list)
    hazardous: bool = False
    updated_at: datetime | None = None


class IngestRuntimeConfigResponse(ContractModel):
    worker_concurrency: int
    quality_preset: IngestionQualityPreset
    ocr_review_confidence_threshold: float
    vision_layout_repair_enabled: bool
    source: str = "workspace"
