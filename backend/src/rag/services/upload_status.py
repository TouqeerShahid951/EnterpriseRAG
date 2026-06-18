"""Derived public upload status details."""

from __future__ import annotations

from dataclasses import dataclass

from ..repositories.document_models import IngestJobRecord
from ..schemas.upload import JobStatusResponse, UploadJobStage, UploadJobStep, UploadJobStepState


@dataclass(frozen=True)
class StepSpec:
    id: UploadJobStage
    label: str
    detail: str
    active_at: int
    complete_at: int


STEPS: tuple[StepSpec, ...] = (
    StepSpec("scheduled", "Scheduled", "Waiting for the scheduled ingestion window.", 0, 0),
    StepSpec("queued", "Queued", "Waiting for the ingestion worker to start.", 0, 5),
    StepSpec("reading_file", "Read file", "Fetching the uploaded document from object storage.", 5, 20),
    StepSpec("parsing_document", "Parse document", "Extracting text, layout, tables, and hierarchy.", 20, 35),
    StepSpec("generating_metadata", "Generate metadata", "Creating document metadata for retrieval filters.", 35, 50),
    StepSpec("chunking_document", "Build chunks", "Creating retrieval chunks and extracted claims.", 50, 60),
    StepSpec("saving_claims", "Save claims", "Persisting extracted claims and conflict pairs.", 60, 65),
    StepSpec("embedding_chunks", "Generate embeddings", "Creating dense and sparse vectors for each chunk.", 65, 78),
    StepSpec("indexing_vectors", "Index vectors", "Writing document vectors to Qdrant.", 78, 92),
    StepSpec("finalizing", "Finalize", "Applying supersession metadata and final job state.", 92, 100),
)
PROCESSING_STEPS = STEPS[1:]

TERMINAL_LABELS: dict[str, tuple[str, str]] = {
    "complete": ("Document indexed", "The document is available for retrieval."),
    "failed": ("Upload failed", "Ingestion stopped before the document was indexed."),
    "human_review": ("Needs review", "The document needs manual review before ingestion can continue."),
    "cancelled": ("Cancelled", "Ingestion was cancelled before the document was indexed."),
}
MAX_INGEST_ATTEMPTS = 3


def build_job_status_response(job: IngestJobRecord) -> JobStatusResponse:
    progress_pct = _normalize_progress(job.progress_pct)
    stage = stage_for_job_status(job.status, progress_pct)
    stage_label, stage_detail = _stage_copy(job.status, stage, job.error_message_safe, job.warnings)
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress_pct=progress_pct,
        stage=stage,
        stage_label=stage_label,
        stage_detail=stage_detail,
        stage_progress=job.stage_progress,
        attempt_count=job.attempt_count,
        max_attempts=MAX_INGEST_ATTEMPTS,
        warnings=list(job.warnings),
        parser_provenance=job.parser_provenance,
        steps=_build_steps(job.status, progress_pct),
        error_code=job.error_code,
        error_message=job.error_message_safe,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        last_heartbeat_at=job.last_heartbeat_at,
    )


def progress_for_status_update(current: IngestJobRecord, *, next_status: str, next_progress_pct: int) -> int:
    progress_pct = _normalize_progress(next_progress_pct)
    if next_status == "failed" and progress_pct >= 100 and current.progress_pct < 100:
        return _normalize_progress(current.progress_pct)
    return progress_pct


def stage_for_job_status(status: str, progress_pct: int) -> UploadJobStage:
    if status in {"complete", "failed", "human_review", "cancelled"}:
        return status  # type: ignore[return-value]
    if status == "queued":
        return "queued"
    if status == "scheduled":
        return "scheduled"
    return _active_processing_step(progress_pct).id


def _stage_copy(status: str, stage: UploadJobStage, error_message: str | None, warnings: tuple[str, ...]) -> tuple[str, str]:
    if status == "failed":
        label, detail = TERMINAL_LABELS["failed"]
        return label, error_message or detail
    if status in TERMINAL_LABELS:
        if status == "complete" and warnings:
            return "Indexed with warnings", "The document is available for retrieval, but optional enrichment was unavailable."
        return TERMINAL_LABELS[status]
    step = _step_by_id(stage)
    return step.label, step.detail


def _build_steps(status: str, progress_pct: int) -> list[UploadJobStep]:
    failed_step = _active_processing_step(progress_pct).id if status == "failed" else None
    review_step = _active_processing_step(progress_pct).id if status == "human_review" else None
    cancelled_step = _active_processing_step(progress_pct).id if status == "cancelled" else None
    steps = STEPS if status == "scheduled" else PROCESSING_STEPS
    return [
        UploadJobStep(
            id=step.id,
            label=step.label,
            detail=step.detail,
            state=_step_state(
                step,
                status=status,
                progress_pct=progress_pct,
                failed_step=failed_step,
                review_step=review_step,
                cancelled_step=cancelled_step,
            ),
        )
        for step in steps
    ]


def _step_state(
    step: StepSpec,
    *,
    status: str,
    progress_pct: int,
    failed_step: UploadJobStage | None,
    review_step: UploadJobStage | None,
    cancelled_step: UploadJobStage | None,
) -> UploadJobStepState:
    if status == "complete":
        return "complete"
    if failed_step == step.id:
        return "failed"
    if review_step == step.id:
        return "needs_review"
    if cancelled_step == step.id:
        return "cancelled"
    if status == "queued":
        return "active" if step.id == "queued" else "pending"
    if status == "scheduled":
        return "active" if step.id == "scheduled" else "pending"
    if progress_pct >= step.complete_at:
        return "complete"
    if progress_pct >= step.active_at:
        return "active"
    return "pending"


def _active_processing_step(progress_pct: int) -> StepSpec:
    if progress_pct >= 100:
        return _step_by_id("finalizing")
    for step in PROCESSING_STEPS:
        if progress_pct < step.complete_at:
            return step
    return PROCESSING_STEPS[-1]


def _step_by_id(step_id: UploadJobStage) -> StepSpec:
    for step in STEPS:
        if step.id == step_id:
            return step
    return STEPS[-1]


def _normalize_progress(progress_pct: int) -> int:
    return max(0, min(100, int(progress_pct)))
