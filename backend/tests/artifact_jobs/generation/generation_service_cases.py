from __future__ import annotations

from datetime import UTC, datetime

from rag.artifact_jobs.adapters.generated_memory import (
    InMemoryGeneratedArtifactRepository,
)
from rag.artifact_jobs.adapters.job_memory import InMemoryArtifactJobRepository
from rag.artifact_jobs.service import ArtifactJobService, _public_stage_timings

from generation_execution_support import DocumentRepository, RecordingQueue
from generation_optimization_support import artifact_job, user_context


def test_stage_timing_serializer_handles_missing_and_partial_timings() -> None:
    assert _public_stage_timings(None) == {}
    assert _public_stage_timings(
        {"planning": {"duration_ms": 25}, "bad": {"started_at": "x"}}
    ) == {
        "planning": {
            "duration_ms": 25,
            "started_at": None,
            "completed_at": None,
        }
    }


def test_artifact_job_summary_exposes_user_facing_progress() -> None:
    job_repo = InMemoryArtifactJobRepository()
    job = artifact_job(repo=job_repo, requested_formats=("docx", "pptx"))
    updated = job_repo.update_job(
        job.id,
        {
            "status": "rendering",
            "stage": "rendering_pptx_slide",
            "progress_pct": 90,
            "stage_progress": {
                "unit": "slides",
                "current": 4,
                "total": 11,
                "label": "Building slide 4 of 11",
            },
        },
    )
    service = ArtifactJobService(
        repo_factory=lambda: job_repo,
        artifact_repo_factory=InMemoryGeneratedArtifactRepository,
        document_repo_factory=DocumentRepository,
        queue_factory=lambda: RecordingQueue(),
        retention_days=1,
    )

    summary = service.summary(updated or job)

    assert summary.stage_label == "Rendering files"
    assert summary.stage_detail == "Building slide 4 of 11"
    assert summary.stage_progress is not None
    assert summary.stage_progress.unit == "slides"
    assert summary.attempt_count == (
        updated.attempt_count if updated else job.attempt_count
    )


def test_retry_resets_artifact_job_attempt_timestamps() -> None:
    job_repo = InMemoryArtifactJobRepository()
    queue = RecordingQueue()
    job = artifact_job(repo=job_repo)
    running, claimed = job_repo.start_attempt(job.id)
    assert claimed
    old_started_at = datetime(2026, 1, 1, tzinfo=UTC)
    failed = job_repo.update_job(
        (running or job).id,
        {
            "status": "failed",
            "stage": "failed",
            "progress_pct": 100,
            "started_at": old_started_at,
            "completed_at": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "last_heartbeat_at": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "error_code": "artifact_generation_failed",
            "error_message_safe": "Generation failed.",
        },
    )
    assert failed is not None
    service = ArtifactJobService(
        repo_factory=lambda: job_repo,
        artifact_repo_factory=InMemoryGeneratedArtifactRepository,
        document_repo_factory=DocumentRepository,
        queue_factory=lambda: queue,
        retention_days=1,
    )

    summary = service.retry(job.id, user_context())

    assert summary.status == "queued"
    assert summary.started_at is None
    assert summary.completed_at is None
    assert summary.last_heartbeat_at is None
    assert summary.updated_at is not None
    assert queue.job_ids == [job.id]
    queued = job_repo.get_job(job.id)
    assert queued is not None
    assert queued.started_at is None
    assert queued.completed_at is None
    assert queued.last_heartbeat_at is None
    restarted, restarted_claimed = job_repo.start_attempt(job.id)
    assert restarted_claimed
    assert restarted is not None
    assert restarted.started_at is not None
    assert restarted.started_at != old_started_at
