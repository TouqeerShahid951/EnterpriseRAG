"""Public API contracts for generated artifacts and artifact jobs."""

from __future__ import annotations

from pydantic import Field

from ..schemas.common import ContractModel
from .contracts import DocumentPlan
from .types import ArtifactFormat, ArtifactJobProgressUnit, ArtifactJobStatus


class GeneratedArtifact(ContractModel):
    id: str
    filename: str
    format: ArtifactFormat
    content_type: str
    size_bytes: int = Field(..., ge=0)
    download_url: str
    created_at: str | None = None


class ArtifactJobStageProgress(ContractModel):
    unit: ArtifactJobProgressUnit
    current: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    label: str | None = None


class ArtifactJobSummary(ContractModel):
    id: str
    status: ArtifactJobStatus
    stage: str
    progress_pct: int = Field(..., ge=0, le=100)
    stage_label: str
    stage_detail: str
    stage_progress: ArtifactJobStageProgress | None = None
    requested_formats: list[ArtifactFormat]
    clarification_questions: list[str] = Field(default_factory=list)
    artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    last_heartbeat_at: str | None = None
    expires_at: str | None = None


class ArtifactStageTiming(ContractModel):
    duration_ms: int = Field(..., ge=0)
    started_at: str | None = None
    completed_at: str | None = None


class ArtifactJobDetail(ArtifactJobSummary):
    original_request: str
    group_path: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    plan: DocumentPlan | None = None
    evidence_manifest: dict[str, object] | None = None
    content_specification: dict[str, object] | None = None
    validation_results: dict[str, object] | None = None
    stage_timings: dict[str, ArtifactStageTiming] = Field(default_factory=dict)
    errors: list[dict[str, object]] = Field(default_factory=list)


class ArtifactClarificationRequest(ContractModel):
    answers: dict[str, str] = Field(..., min_length=1, max_length=5)


class ArtifactJobMutationResponse(ContractModel):
    job: ArtifactJobSummary
