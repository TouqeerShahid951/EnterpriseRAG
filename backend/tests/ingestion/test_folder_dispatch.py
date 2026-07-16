from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import logging

import pytest

from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.ingestion.folders.adapters.memory import (
    InMemoryFolderScheduleRepository,
)
from rag.ingestion.folders.config import FolderIngestionConfig
from rag.ingestion.folders.dispatch import dispatch_due_schedules
from rag.ingestion.delivery.service import (
    IngestDeliveryService,
    dispatch_pending_deliveries,
)
from rag.ingestion.queue import InMemoryIngestQueue


FOLDER_CONFIG = FolderIngestionConfig(
    default_timezone="Asia/Karachi",
    sources_root="/folder-sources",
    snapshot_max_files=100,
    snapshot_max_bytes=5 * 1024 * 1024 * 1024,
    upload_max_bytes=50 * 1024 * 1024,
)


class _EmptyMinioSource:
    def list_objects(self, **kwargs):
        return []


class _FailingMinioSource:
    def list_objects(self, **kwargs):
        raise RuntimeError("source unavailable")


class _FailingQueue:
    def __init__(self) -> None:
        self.attempts = 0

    def enqueue(self, message) -> None:
        self.attempts += 1
        raise RuntimeError("queue unavailable")

    def cancel(self, job_id: str) -> None:
        _ = job_id


@pytest.mark.parametrize(
    ("source_type", "minio_source"),
    [
        pytest.param("unknown", _EmptyMinioSource(), id="unknown-source-type"),
        pytest.param("minio_prefix", _FailingMinioSource(), id="failing-source"),
    ],
)
def test_dispatch_failure_is_recorded_and_does_not_stop_later_schedules(
    source_type,
    minio_source,
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = datetime.now(UTC)
    schedule_repo = InMemoryFolderScheduleRepository()
    failed_schedule = _create_due_schedule(
        schedule_repo,
        now=now,
        source_type=source_type,
        name="Failure",
    )
    later_schedule = _create_due_schedule(
        schedule_repo,
        now=now,
        source_type="snapshot",
        name="Later snapshot",
    )
    caplog.set_level(logging.ERROR, logger="rag.ingestion.folders.dispatch")

    dispatched = dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=InMemoryDocumentRepository(),
        job_repo=InMemoryDocumentRepository(),
        queue=InMemoryIngestQueue(),
        minio_source=minio_source,
        config=FOLDER_CONFIG,
        now=now,
    )

    failed_run = schedule_repo.list_runs(failed_schedule.id)[0]
    assert failed_run.status == "failed"
    assert failed_run.error_code == "folder_dispatch_failed"
    assert schedule_repo.get_schedule(failed_schedule.id).status == "failed"
    assert dispatched == [later_schedule.id]
    assert schedule_repo.get_schedule(later_schedule.id).status == "complete"
    assert any(
        record.levelno >= logging.ERROR
        and getattr(record, "folder_schedule_id", None) == failed_schedule.id
        for record in caplog.records
    )


def test_enqueue_failure_remains_retryable_and_queues_once_after_resume() -> None:
    now = datetime.now(UTC)
    schedule_repo = InMemoryFolderScheduleRepository()
    document_repo = InMemoryDocumentRepository()
    schedule = _create_due_schedule(
        schedule_repo,
        now=now,
        source_type="snapshot",
        name="Queued snapshot",
    )
    run = schedule_repo.create_run(
        schedule_id=schedule.id,
        status="scheduled",
        due_at=now,
    )
    document = document_repo.create_document(
        title="case.json",
        source_id="folder:snapshot:case.json",
        group_path=schedule.group_path,
        clearance_level=schedule.clearance_level,
        doc_type=schedule.doc_type,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=schedule.created_by,
        file_path="memory://case.json",
        content_hash="a" * 64,
        pending_supersedes=[],
        ingest_status="scheduled",
    )
    job = document_repo.create_ingest_job(
        doc_id=document.id,
        status="scheduled",
        progress_pct=0,
        origin="folder",
    )
    item = schedule_repo.create_run_item(
        run_id=run.id,
        schedule_id=schedule.id,
        source_path="case.json",
        filename="case.json",
        object_path=document.file_path,
        content_hash=document.content_hash,
        size_bytes=2,
        content_type="application/json",
        status="scheduled",
        document_id=document.id,
        job_id=job.id,
    )
    queue = _FailingQueue()

    dispatched = dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=_EmptyMinioSource(),
        config=FOLDER_CONFIG,
        now=now,
    )

    assert queue.attempts == 1
    assert dispatched == [schedule.id]
    assert schedule_repo.get_schedule(schedule.id).status == "complete"
    completed_run = schedule_repo.get_run(run.id)
    assert completed_run is not None and completed_run.status == "complete"
    queued_item = schedule_repo.list_run_items(run.id)[0]
    assert queued_item.id == item.id
    assert queued_item.status == "queued"
    assert queued_item.skip_code is None
    queued_job = document_repo.get_ingest_job(job.id)
    assert queued_job is not None
    assert queued_job.status == "queued"
    assert queued_job.failure_attempt_count == 0
    assert queued_job.delivery_count == 1

    healthy_queue = InMemoryIngestQueue()
    delivery = IngestDeliveryService(document_repo)
    retried = dispatch_pending_deliveries(
        delivery,
        healthy_queue,
        now=now + timedelta(seconds=6),
    )

    assert retried.published_count == 1
    assert len(healthy_queue.messages) == 1
    assert dispatch_pending_deliveries(
        delivery,
        healthy_queue,
        now=now + timedelta(seconds=7),
    ).claimed_count == 0
    assert len(healthy_queue.messages) == 1


def test_recurring_dispatch_uses_injected_default_for_blank_timezone() -> None:
    now = datetime(2030, 1, 7, 12, 0, tzinfo=UTC)
    schedule_repo = InMemoryFolderScheduleRepository()
    schedule = schedule_repo.create_schedule(
        name="Legacy recurring prefix",
        source_type="minio_prefix",
        schedule_type="recurring",
        status="active",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        timezone="",
        scheduled_at=None,
        recurrence={
            "days_of_week": [0],
            "start_time": "09:00",
            "end_time": "10:00",
        },
        source_config={"bucket": "documents", "prefix": "incoming/"},
        created_by="user-1",
        next_run_at=now,
    )

    dispatched = dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=InMemoryDocumentRepository(),
        job_repo=InMemoryDocumentRepository(),
        queue=InMemoryIngestQueue(),
        minio_source=_EmptyMinioSource(),
        config=replace(FOLDER_CONFIG, default_timezone="America/New_York"),
        now=now,
    )

    assert dispatched == [schedule.id]
    updated = schedule_repo.get_schedule(schedule.id)
    assert updated is not None
    assert updated.next_run_at == datetime(2030, 1, 7, 14, 0, tzinfo=UTC)


def _create_due_schedule(
    repository: InMemoryFolderScheduleRepository,
    *,
    now: datetime,
    source_type: str,
    name: str,
):
    source_config = (
        {"bucket": "documents", "prefix": "incoming/"}
        if source_type == "minio_prefix"
        else {}
    )
    return repository.create_schedule(
        name=name,
        source_type=source_type,
        schedule_type="one_time",
        status="scheduled",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="case record",
        effective_date=None,
        expiry_date=None,
        description=None,
        timezone="Asia/Karachi",
        scheduled_at=now,
        recurrence={},
        source_config=source_config,
        created_by="user-1",
        next_run_at=now,
    )
