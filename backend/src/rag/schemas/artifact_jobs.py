"""Public API contracts for asynchronous artifact generation."""

from __future__ import annotations

from pydantic import Field

from ..artifact_jobs.contracts import DocumentPlan
from .common import ContractModel
from .query import ArtifactJobSummary


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
    attempt_count: int = 0
    max_attempts: int = 3
    started_at: str | None = None
    completed_at: str | None = None
    last_heartbeat_at: str | None = None


class ArtifactClarificationRequest(ContractModel):
    answers: dict[str, str] = Field(..., min_length=1, max_length=5)


class ArtifactJobMutationResponse(ContractModel):
    job: ArtifactJobSummary
