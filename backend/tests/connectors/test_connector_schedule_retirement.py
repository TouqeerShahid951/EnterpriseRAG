from __future__ import annotations

from datetime import UTC, datetime

from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.ingestion.adapters.folder_schedule_memory import InMemoryFolderScheduleRepository
from rag.services.connector_schedule_retirement import retire_connector_schedules


class FakeQdrant:
    def __init__(self) -> None:
        self.deleted_doc_ids: list[str] = []

    def delete_document_points(self, doc_id: str) -> None:
        self.deleted_doc_ids.append(doc_id)


class FakeStorage:
    def __init__(self) -> None:
        self.deleted_paths: list[str] = []

    def delete(self, object_path: str) -> None:
        self.deleted_paths.append(object_path)


def test_retire_connector_schedules_deletes_only_connector_snapshot_documents() -> None:
    schedule_repo = InMemoryFolderScheduleRepository()
    document_repo = InMemoryDocumentRepository()
    qdrant = FakeQdrant()
    storage = FakeStorage()
    schedule = schedule_repo.create_schedule(
        schedule_id="schedule-1",
        name="Legacy DB sync",
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
        recurrence={},
        source_config={"connector_profile_id": "profile-1", "connector_type": "fake"},
        created_by="admin",
        next_run_at=datetime.now(UTC),
    )
    run = schedule_repo.create_run(schedule_id=schedule.id, status="complete", due_at=datetime.now(UTC))
    connector_doc = document_repo.create_document(
        title="Connector row",
        source_id=f"connector:{schedule.id}:row-1:hash",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="case record",
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by="admin",
        file_path="memory://connector-row.json",
        content_hash="connector-hash",
        pending_supersedes=[],
        ingest_status="complete",
    )
    unrelated_doc = document_repo.create_document(
        title="Manual upload",
        source_id="upload:manual",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="policy",
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by="admin",
        file_path="memory://manual.pdf",
        content_hash="manual-hash",
        pending_supersedes=[],
        ingest_status="complete",
    )
    schedule_repo.create_run_item(
        run_id=run.id,
        schedule_id=schedule.id,
        source_path="row-1",
        filename="row-1.json",
        object_path="memory://connector-row.json",
        content_hash="connector-hash",
        size_bytes=10,
        content_type="application/json",
        status="queued",
        document_id=connector_doc.id,
    )
    schedule_repo.create_run_item(
        run_id=run.id,
        schedule_id=schedule.id,
        source_path="manual",
        filename="manual.pdf",
        object_path="memory://manual.pdf",
        content_hash="manual-hash",
        size_bytes=10,
        content_type="application/pdf",
        status="queued",
        document_id=unrelated_doc.id,
    )

    result = retire_connector_schedules(
        schedule_repo=schedule_repo,
        document_repo=document_repo,
        qdrant=qdrant,
        storage=storage,
    )

    assert result.schedules_deleted == 1
    assert result.documents_deleted == 1
    assert result.vectors_deleted == 1
    assert result.files_deleted == 1
    assert result.skipped_documents == 1
    assert qdrant.deleted_doc_ids == [connector_doc.id]
    assert storage.deleted_paths == ["memory://connector-row.json"]
    assert schedule_repo.get_schedule(schedule.id) is None
    assert document_repo.get_document(connector_doc.id, include_deleted=True) is None
    assert document_repo.get_document(unrelated_doc.id) is not None
