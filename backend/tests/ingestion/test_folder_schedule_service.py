from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.documents.adapters.file_scanning import NoopFileScanner
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.scanning import ScannerUnavailableError
from rag.documents.storage import StoredUpload
from rag.ingestion.folders.adapters.memory import (
    InMemoryFolderScheduleRepository,
)
from rag.ingestion.folders.adapters.sources import LocalFileSystemSource
from rag.ingestion.folders.config import FolderIngestionConfig
from rag.ingestion.folders.errors import FolderIngestionRejected
from rag.ingestion.folders.snapshot_schedules import create_snapshot_schedule
from rag.ingestion.folders.source_schedules import create_local_folder_schedule


PDF_CONTENT = b"%PDF-1.7\nfolder schedule service\n%%EOF"
CONFIG = FolderIngestionConfig(
    default_timezone="Asia/Karachi",
    sources_root="/folder-sources",
    snapshot_max_files=100,
    snapshot_max_bytes=5 * 1024 * 1024,
    upload_max_bytes=1024 * 1024,
)


class MemoryUpload:
    def __init__(self, filename: str, content: bytes = PDF_CONTENT) -> None:
        self.filename = filename
        self.content_type = "application/pdf"
        self._content = content
        self._position = 0

    async def read(self, size: int = -1) -> bytes:
        end = len(self._content) if size < 0 else self._position + size
        result = self._content[self._position : end]
        self._position += len(result)
        return result

    async def seek(self, offset: int) -> None:
        self._position = offset


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
        object_path = f"memory://{filename}"
        self.objects[object_path] = content
        return StoredUpload(
            object_path=object_path,
            size_bytes=len(content),
            content_type=content_type,
        )


class UnavailableScanner:
    def scan(self, content: bytes) -> None:
        _ = content
        raise ScannerUnavailableError("connection refused")


def test_unknown_group_is_an_explicit_invalid_rejection(tmp_path) -> None:
    identity_repo, user = _identity()

    with pytest.raises(FolderIngestionRejected) as raised:
        _create_local_schedule(
            path=str(tmp_path),
            group_path="/missing",
            user=user,
            identity_repo=identity_repo,
        )

    assert (raised.value.category, raised.value.code) == (
        "invalid",
        "group_not_found",
    )


def test_clearance_above_actor_is_an_explicit_forbidden_rejection(tmp_path) -> None:
    identity_repo, user = _identity()

    with pytest.raises(FolderIngestionRejected) as raised:
        _create_local_schedule(
            path=str(tmp_path),
            clearance_level="NATO_SECRET",
            user=user,
            identity_repo=identity_repo,
        )

    assert (raised.value.category, raised.value.code) == (
        "forbidden",
        "folder_schedule_clearance_forbidden",
    )


def test_snapshot_file_limit_comes_from_injected_config() -> None:
    context = _snapshot_context()

    with pytest.raises(FolderIngestionRejected) as raised:
        asyncio.run(
            create_snapshot_schedule(
                files=[MemoryUpload("first.pdf"), MemoryUpload("second.pdf")],
                relative_paths=["first.pdf", "second.pdf"],
                config=replace(CONFIG, snapshot_max_files=1),
                scanner=NoopFileScanner(),
                **context,
            )
        )

    assert (raised.value.category, raised.value.code) == (
        "too_large",
        "folder_file_limit",
    )
    assert context["schedule_repo"].list_schedules() == []


def test_snapshot_schedule_stages_an_accepted_file() -> None:
    context = _snapshot_context()

    schedule = asyncio.run(
        create_snapshot_schedule(
            files=[MemoryUpload("case.pdf")],
            relative_paths=["cases/case.pdf"],
            config=CONFIG,
            scanner=NoopFileScanner(),
            **context,
        )
    )

    schedule_repo = context["schedule_repo"]
    assert isinstance(schedule_repo, InMemoryFolderScheduleRepository)
    runs = schedule_repo.list_runs(schedule.id)
    items = schedule_repo.list_run_items(runs[0].id)
    assert schedule.source_type == "snapshot"
    assert runs[0].status == "scheduled"
    assert len(items) == 1
    assert items[0].source_path == "cases/case.pdf"
    assert items[0].status == "scheduled"
    assert items[0].document_id
    assert items[0].job_id
    storage = context["storage"]
    assert isinstance(storage, MemoryStorage)
    assert storage.objects == {"memory://case.pdf": PDF_CONTENT}


def test_scanner_outage_is_not_masked_as_an_empty_folder() -> None:
    context = _snapshot_context()

    with pytest.raises(FolderIngestionRejected) as raised:
        asyncio.run(
            create_snapshot_schedule(
                files=[MemoryUpload("case.pdf")],
                relative_paths=["case.pdf"],
                config=CONFIG,
                scanner=UnavailableScanner(),
                **context,
            )
        )

    assert (raised.value.category, raised.value.code) == (
        "unavailable",
        "scanner_unavailable",
    )
    assert context["schedule_repo"].list_schedules() == []
    assert context["storage"].objects == {}


def test_local_schedule_uses_injected_filesystem_source_and_config(tmp_path) -> None:
    watch_root = tmp_path / "watch"
    watch_root.mkdir()
    identity_repo, user = _identity()
    document_repo = InMemoryDocumentRepository()

    schedule = create_local_folder_schedule(
        name="Local cases",
        path=str(watch_root / ".." / "watch"),
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        effective_date=None,
        expiry_date=None,
        doc_type="case record",
        description=None,
        schedule_type="one_time",
        timezone_name="",
        scheduled_at=datetime(2030, 1, 1, 10, 0),
        recurrence={},
        user=user,
        identity_repo=identity_repo,
        document_repo=document_repo,
        schedule_repo=InMemoryFolderScheduleRepository(),
        local_folder_source=LocalFileSystemSource(),
        config=replace(CONFIG, default_timezone="America/New_York"),
    )

    assert schedule.source_config == {"path": str(watch_root.resolve())}
    assert schedule.timezone == "America/New_York"
    assert schedule.next_run_at == datetime(2030, 1, 1, 15, 0, tzinfo=UTC)
    assert document_repo.audit_events[0]["event_type"] == (
        "folder_ingest.schedule_created"
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


def _create_local_schedule(
    *,
    path: str,
    user,
    identity_repo: InMemoryIdentityRepository,
    group_path: str = "/ops",
    clearance_level: str = "NATO_RESTRICTED",
):
    return create_local_folder_schedule(
        name="Local cases",
        path=path,
        group_path=group_path,
        clearance_level=clearance_level,
        effective_date=None,
        expiry_date=None,
        doc_type=None,
        description=None,
        schedule_type="one_time",
        timezone_name="UTC",
        scheduled_at=datetime(2030, 1, 1, tzinfo=UTC),
        recurrence={},
        user=user,
        identity_repo=identity_repo,
        document_repo=InMemoryDocumentRepository(),
        schedule_repo=InMemoryFolderScheduleRepository(),
        local_folder_source=LocalFileSystemSource(),
        config=CONFIG,
    )


def _snapshot_context() -> dict[str, object]:
    identity_repo, user = _identity()
    document_repo = InMemoryDocumentRepository()
    return {
        "name": "Snapshot cases",
        "group_path": "/ops",
        "clearance_level": "NATO_RESTRICTED",
        "effective_date": None,
        "expiry_date": None,
        "doc_type": None,
        "description": None,
        "schedule_type": "one_time",
        "timezone_name": "UTC",
        "scheduled_at": datetime(2030, 1, 1, tzinfo=UTC),
        "recurrence": {},
        "user": user,
        "identity_repo": identity_repo,
        "document_repo": document_repo,
        "job_repo": document_repo,
        "schedule_repo": InMemoryFolderScheduleRepository(),
        "storage": MemoryStorage(),
    }
