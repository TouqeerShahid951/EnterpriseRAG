from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.ingestion.job_models import IngestJobAccess, IngestJobFilters
from rag.ingestion.monitoring import (
    IngestWorkerStatusUnavailable,
    inspect_stale_ingest_jobs,
    requeue_stale_job,
    search_visible_ingest_jobs,
    summarize_visible_ingest_jobs,
)
from rag.ingestion.queue import InMemoryIngestQueue
from rag.ingestion.worker_control import WorkerCapacity, WorkerControlResult


def test_visible_job_query_short_circuits_when_metadata_is_forbidden() -> None:
    page = search_visible_ingest_jobs(
        repo=_UnexpectedSearchRepository(),  # type: ignore[arg-type]
        access=_access(),
        filters=IngestJobFilters(),
        can_view=False,
        limit=20,
        offset=10,
    )

    assert page.items == ()
    assert page.total == 0


def test_summary_counts_history_but_only_latest_job_needs_attention() -> None:
    repo = InMemoryDocumentRepository()
    document = _document(repo)
    failed = repo.create_ingest_job(
        doc_id=document.id,
        status="failed",
        progress_pct=75,
        origin="upload",
    )
    retry = repo.create_ingest_job(
        doc_id=document.id,
        status="queued",
        progress_pct=0,
        origin="reingest",
        retry_of_job_id=failed.id,
    )
    repo.update_ingest_job(retry.id, status="complete", progress_pct=100)

    summary = summarize_visible_ingest_jobs(
        repo=repo,
        access=_access(),
        filters=IngestJobFilters(),
        can_view=True,
    )

    assert summary.total == 2
    assert summary.status_counts == {"complete": 1, "failed": 1}
    assert summary.stage_counts == {"complete": 1, "failed": 1}
    assert summary.origin_counts == {"reingest": 1, "upload": 1}
    assert summary.needs_attention == 0


def test_stale_recovery_refuses_to_continue_without_worker_snapshot() -> None:
    repo = InMemoryDocumentRepository()

    with pytest.raises(IngestWorkerStatusUnavailable):
        inspect_stale_ingest_jobs(
            document_repo=repo,
            job_repo=repo,
            control=_FailingControl(),  # type: ignore[arg-type]
            desired_concurrency=2,
            stale_after_seconds=120,
        )


def test_stale_requeue_uses_verified_activity_and_records_audit() -> None:
    repo = InMemoryDocumentRepository()
    document = _document(repo)
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="processing",
        progress_pct=40,
        origin="upload",
    )
    old_timestamp = datetime.now(UTC) - timedelta(minutes=10)
    repo._jobs[job.id] = replace(  # noqa: SLF001 - focused in-memory fixture setup
        job,
        created_at=old_timestamp,
        updated_at=old_timestamp,
        last_heartbeat_at=old_timestamp,
    )
    queue = InMemoryIngestQueue()

    requeued = requeue_stale_job(
        document_repo=repo,
        job_repo=repo,
        queue=queue,
        control=_HealthyControl(),  # type: ignore[arg-type]
        desired_concurrency=2,
        stale_after_seconds=120,
        job_id=job.id,
        actor_id="admin-1",
        audit_event_type="admin.ingest.requeued",
    )

    assert requeued.status == "queued"
    assert requeued.failure_attempt_count == 1
    assert queue.messages[0].job_id == job.id
    assert repo.audit_events[-1]["event_type"] == "admin.ingest.requeued"
    assert repo.audit_events[-1]["actor_id"] == "admin-1"
    assert repo.audit_events[-1]["payload"]["failure_attempt_count"] == 1


class _UnexpectedSearchRepository:
    def search_visible_ingest_jobs(self, **_kwargs: object) -> object:
        raise AssertionError("repository must not be queried")


class _FailingControl:
    def snapshot(self, desired_concurrency: int) -> WorkerControlResult:
        _ = desired_concurrency
        raise ConnectionError("worker control is unavailable")


class _HealthyControl:
    def snapshot(self, desired_concurrency: int) -> WorkerControlResult:
        return WorkerControlResult(
            desired_concurrency=desired_concurrency,
            workers=(
                WorkerCapacity(
                    name="ingestion-worker@test",
                    pool_size=desired_concurrency,
                    active_jobs=0,
                ),
            ),
            apply_status="applied",
        )


def _access() -> IngestJobAccess:
    return IngestJobAccess(
        clearance_levels=("NATO_RESTRICTED",),
        group_paths=("/ops",),
    )


def _document(repo: InMemoryDocumentRepository):
    return repo.create_document(
        title="Document.pdf",
        source_id="source-1",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="pdf",
        effective_date=None,
        expiry_date=None,
        description=None,
        pending_supersedes=[],
        content_hash="hash-1",
        uploaded_by="user-1",
        file_path="memory://document.pdf",
        ingest_status="queued",
    )
