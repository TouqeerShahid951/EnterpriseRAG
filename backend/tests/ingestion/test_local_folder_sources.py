from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.storage import StoredUpload
from rag.ingestion.folders.adapters.memory import InMemoryFolderScheduleRepository
from rag.ingestion.folders.adapters.sources import LocalFileSystemSource
from rag.ingestion.folders.config import FolderIngestionConfig
from rag.ingestion.folders.dispatch import dispatch_due_schedules
from rag.ingestion.folders.service import create_local_folder_schedule
from rag.ingestion.folders.sources import list_local_folder_directories
from rag.ingestion.queue import InMemoryIngestQueue


FOLDER_CONFIG = FolderIngestionConfig(
    default_timezone="Asia/Karachi",
    sources_root="/folder-sources",
    snapshot_max_files=100,
    snapshot_max_bytes=5 * 1024 * 1024 * 1024,
    upload_max_bytes=50 * 1024 * 1024,
)


class FakeMinioSource:
    def list_objects(self, **kwargs):
        return []


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> StoredUpload:
        object_path = f"memory://{len(self.objects)}-{filename}"
        self.objects[object_path] = content
        return StoredUpload(
            object_path=object_path,
            size_bytes=len(content),
            content_type=content_type,
        )


def test_dispatch_cancels_legacy_connector_schedules_without_syncing() -> None:
    _identity_repo, user = _identity()
    document_repo = InMemoryDocumentRepository()
    schedule_repo = InMemoryFolderScheduleRepository()
    queue = InMemoryIngestQueue()
    now = datetime.now(UTC)
    schedule = schedule_repo.create_schedule(
        name="Legacy connector sync",
        source_type="connector",
        schedule_type="recurring",
        status="active",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="case record",
        effective_date=None,
        expiry_date=None,
        description=None,
        timezone="Asia/Karachi",
        scheduled_at=None,
        recurrence={
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
            "start_time": "00:00",
            "end_time": "23:59",
        },
        source_config={
            "connector_profile_id": "profile-1",
            "connector_type": "fake",
        },
        created_by=user.id,
        next_run_at=now,
    )

    dispatched = dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        config=FOLDER_CONFIG,
        now=now,
    )

    assert dispatched == []
    assert queue.messages == []
    assert schedule_repo.list_runs(schedule.id) == []
    assert schedule_repo.get_schedule(schedule.id).status == "cancelled"


def test_local_folder_watcher_syncs_new_and_changed_files(tmp_path) -> None:
    watch_root = tmp_path / "watch"
    watch_root.mkdir()
    source_file = watch_root / "case.json"
    source_file.write_text('{"id":"1","status":"open"}', encoding="utf-8")
    (watch_root / "notes.txt").write_text("unsupported", encoding="utf-8")

    identity_repo, user = _identity()
    document_repo = InMemoryDocumentRepository()
    schedule_repo = InMemoryFolderScheduleRepository()
    queue = InMemoryIngestQueue()
    storage = MemoryStorage()
    local_source = LocalFileSystemSource()
    schedule = create_local_folder_schedule(
        name="Case folder watcher",
        path=str(watch_root),
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        effective_date=None,
        expiry_date=None,
        doc_type="case record",
        description=None,
        schedule_type="recurring",
        timezone_name="Asia/Karachi",
        scheduled_at=None,
        recurrence={
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
            "start_time": "00:00",
            "end_time": "23:59",
        },
        user=user,
        identity_repo=identity_repo,
        document_repo=document_repo,
        schedule_repo=schedule_repo,
        local_folder_source=local_source,
        config=FOLDER_CONFIG,
    )

    now = datetime.now(UTC)
    dispatched = dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        local_folder_source=local_source,
        storage=storage,
        config=FOLDER_CONFIG,
        now=now,
    )

    assert dispatched == [schedule.id]
    assert len(queue.messages) == 1
    assert len(storage.objects) == 1
    assert {
        item.skip_code
        for run in schedule_repo.list_runs(schedule.id)
        for item in schedule_repo.list_run_items(run.id)
    } >= {"unsupported_file_type"}

    schedule_repo.update_schedule_next_run(
        schedule.id,
        status="active",
        next_run_at=now,
    )
    dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        local_folder_source=local_source,
        storage=storage,
        config=FOLDER_CONFIG,
        now=now,
    )

    assert len(queue.messages) == 1
    assert any(
        item.skip_code == "unchanged_source"
        for run in schedule_repo.list_runs(schedule.id)
        for item in schedule_repo.list_run_items(run.id)
    )

    source_file.write_text('{"id":"1","status":"closed"}', encoding="utf-8")
    schedule_repo.update_schedule_next_run(
        schedule.id,
        status="active",
        next_run_at=now,
    )
    dispatch_due_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        queue=queue,
        minio_source=FakeMinioSource(),
        local_folder_source=local_source,
        storage=storage,
        config=FOLDER_CONFIG,
        now=now,
    )

    assert len(queue.messages) == 2
    assert queue.messages[-1].supersedes
    assert len(document_repo.list_documents()) == 2


def test_local_folder_browser_lists_directories_under_root(tmp_path) -> None:
    root = tmp_path / "folder-sources"
    cases = root / "cases"
    nested = cases / "incoming"
    empty = root / "empty"
    nested.mkdir(parents=True)
    empty.mkdir(parents=True)
    (root / "case.json").write_text("{}", encoding="utf-8")

    source = LocalFileSystemSource()
    browse_root, current, parent, items = list_local_folder_directories(
        source=source,
        root_path=str(root),
    )

    assert browse_root == root.resolve()
    assert current == root.resolve()
    assert parent is None
    assert [(item.name, item.has_children) for item in items] == [
        ("cases", True),
        ("empty", False),
    ]

    _, current, parent, items = list_local_folder_directories(
        source=source,
        root_path=str(root),
        current_path=str(cases),
    )

    assert current == cases.resolve()
    assert parent == root.resolve()
    assert [item.name for item in items] == ["incoming"]

    with pytest.raises(RuntimeError):
        list_local_folder_directories(
            source=source,
            root_path=str(root),
            current_path=str(tmp_path),
        )


def _identity():
    repo = InMemoryIdentityRepository()
    repo.create_group(path="/ops", name="Ops")
    user = repo.create_user(
        email="space-admin@example.test",
        name="Space Admin",
        password_hash="hash",
        group_paths=["/ops"],
        is_active=True,
        account_type="space_admin",
        clearance_level="NATO_RESTRICTED",
    )
    return repo, user
