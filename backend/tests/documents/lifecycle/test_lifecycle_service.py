from __future__ import annotations

from uuid import uuid4

import pytest

from rag.auth.identity_models import UserRecord
from rag.documents.access_scope.ports import (
    DocumentGraphCleanupError,
    DocumentGraphCleanupResult,
)
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.lifecycle.ports import DocumentVectorIndexError
from rag.documents.lifecycle.service import (
    DeleteDocumentCommand,
    DocumentLifecycleRejected,
    DocumentLifecycleService,
    RestoreDocumentCommand,
)
from rag.documents.models import DocumentRecord
from rag.documents.storage import StoredUploadContent
from rag.ingestion.contracts import IngestJobPayload


class RecordingRepository(InMemoryDocumentRepository):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def restore_document(self, document_id: str) -> DocumentRecord | None:
        self.events.append("database:restore")
        return super().restore_document(document_id)

    def soft_delete_document(self, document_id: str) -> DocumentRecord | None:
        self.events.append("database:soft_delete")
        return super().soft_delete_document(document_id)

    def permanently_delete_document(
        self,
        document_id: str,
    ) -> DocumentRecord | None:
        self.events.append("database:permanent_delete")
        return super().permanently_delete_document(document_id)


class FakeStorage:
    def __init__(
        self,
        events: list[str],
        *,
        read_error: str | None = None,
        delete_error: str | None = None,
        filename: str = "document.pdf",
        content_type: str | None = "application/pdf",
    ) -> None:
        self.events = events
        self.read_error = read_error
        self.delete_error = delete_error
        self.filename = filename
        self.content_type = content_type

    def read(self, object_path: str) -> StoredUploadContent:
        self.events.append(f"storage:read:{object_path}")
        if self.read_error:
            raise RuntimeError(self.read_error)
        return StoredUploadContent(
            content=b"source",
            content_type=self.content_type,
            filename=self.filename,
        )

    def delete(self, object_path: str) -> None:
        self.events.append(f"storage:delete:{object_path}")
        if self.delete_error:
            raise RuntimeError(self.delete_error)


class FakeImageStorage:
    def __init__(
        self,
        events: list[str],
        *,
        fail_on: str | None = None,
    ) -> None:
        self.events = events
        self.fail_on = fail_on

    def delete(self, object_path: str) -> None:
        self.events.append(f"image:delete:{object_path}")
        if object_path == self.fail_on:
            raise RuntimeError("image store unavailable")


class FakeIngestQueue:
    def __init__(self, events: list[str], *, error: str | None = None) -> None:
        self.events = events
        self.error = error
        self.messages: list[IngestJobPayload] = []

    def enqueue(self, message: IngestJobPayload) -> None:
        self.events.append("ingest:enqueue")
        if self.error:
            raise RuntimeError(self.error)
        self.messages.append(message)


class FakeVectorIndex:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def delete_document_points(self, document_id: str) -> None:
        self.events.append(f"vectors:delete:{document_id}")
        if self.fail:
            raise DocumentVectorIndexError("vector store unavailable")


class FakeGraphCleanup:
    def __init__(
        self,
        events: list[str],
        *,
        fail: bool = False,
        result_partition: str | None = "/ops|clearance:1",
    ) -> None:
        self.events = events
        self.fail = fail
        self.result_partition = result_partition

    def partition_key_for(self, document: DocumentRecord) -> str:
        return f"{document.group_path}|clearance:1"

    def delete_document(
        self,
        *,
        document_id: str,
        partition_key: str,
    ) -> DocumentGraphCleanupResult:
        self.events.append(f"graph:delete:{document_id}")
        if self.fail:
            raise DocumentGraphCleanupError("graph store unavailable")
        return DocumentGraphCleanupResult(
            status="complete",
            partition_key=self.result_partition,
        )


class FakeGraphQueue:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail
        self.messages: list[dict[str, str]] = []

    def enqueue_partition_rebuild(
        self,
        *,
        document_id: str,
        partition_key: str,
        reason: str,
    ) -> None:
        self.events.append(f"graph:rebuild:{document_id}")
        if self.fail:
            raise RuntimeError("broker unavailable")
        self.messages.append(
            {
                "document_id": document_id,
                "partition_key": partition_key,
                "reason": reason,
            }
        )


def test_restore_reads_source_restores_then_queues_and_audits() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)
    repo.soft_delete_document(document.id)
    events.clear()
    storage = FakeStorage(events, filename="", content_type=None)
    ingest_queue = FakeIngestQueue(events)

    result = _service(
        repo,
        events,
        storage=storage,
        ingest_queue=ingest_queue,
    ).restore(RestoreDocumentCommand(document_id=document.id, actor=actor))

    restored = repo.get_document(document.id, include_deleted=True)
    job = repo.get_ingest_job(result.job_id)
    assert restored is not None and restored.deleted_at is None
    assert job is not None and job.status == "queued" and job.origin == "restore"
    assert ingest_queue.messages[0].content_type == "application/pdf"
    assert ingest_queue.messages[0].acl_group_paths == ["/ops"]
    assert events == [
        "storage:read:memory://document.pdf",
        "database:restore",
        "ingest:enqueue",
    ]
    assert repo.audit_events[-1]["event_type"] == "documents.restore"
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_restore_rejects_non_writer_before_reading_source() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    owner = _user("contributor")
    document = _document(repo, actor=owner)
    repo.soft_delete_document(document.id)
    events.clear()

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(repo, events).restore(
            RestoreDocumentCommand(
                document_id=document.id,
                actor=_user("member"),
            )
        )

    assert exc_info.value.category == "forbidden"
    assert exc_info.value.code == "document_forbidden"
    assert events == []
    assert repo.list_ingest_jobs() == []


def test_restore_rejects_active_job_before_reading_source() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)
    repo.soft_delete_document(document.id)
    existing = repo.create_ingest_job(
        doc_id=document.id,
        status="processing",
        progress_pct=20,
        origin="upload",
    )
    events.clear()

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(repo, events).restore(
            RestoreDocumentCommand(document_id=document.id, actor=actor)
        )

    assert exc_info.value.code == "document_ingest_active"
    assert events == []
    assert [job.id for job in repo.list_ingest_jobs()] == [existing.id]


@pytest.mark.parametrize(
    ("file_path", "read_error"),
    [(None, None), ("memory://missing.pdf", "not found")],
)
def test_restore_rejects_missing_source_before_database_restore(
    file_path: str | None,
    read_error: str | None,
) -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor, file_path=file_path)
    repo.soft_delete_document(document.id)
    events.clear()

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(
            repo,
            events,
            storage=FakeStorage(events, read_error=read_error),
        ).restore(RestoreDocumentCommand(document_id=document.id, actor=actor))

    assert exc_info.value.code == "document_source_missing"
    assert "database:restore" not in events
    assert repo.get_document(document.id, include_deleted=True).deleted_at is not None  # type: ignore[union-attr]


def test_restore_queue_failure_keeps_restored_document_and_queued_job() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)
    repo.soft_delete_document(document.id)
    events.clear()

    result = _service(
        repo,
        events,
        ingest_queue=FakeIngestQueue(events, error="redis unavailable"),
    ).restore(RestoreDocumentCommand(document_id=document.id, actor=actor))

    jobs = repo.list_ingest_jobs()
    restored = repo.get_document(document.id, include_deleted=True)
    assert restored is not None and restored.deleted_at is None
    assert len(jobs) == 1 and jobs[0].id == result.job_id
    assert jobs[0].status == "queued"
    assert jobs[0].failure_attempt_count == 0
    assert jobs[0].active_delivery_id is not None
    assert events == [
        "storage:read:memory://document.pdf",
        "database:restore",
        "ingest:enqueue",
    ]
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_soft_delete_cleans_graph_and_vectors_before_database_and_rebuild() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)

    result = _service(repo, events).soft_delete(
        DeleteDocumentCommand(document_id=document.id, actor=actor)
    )

    assert result.status == "soft_deleted"
    assert events == [
        f"graph:delete:{document.id}",
        f"vectors:delete:{document.id}",
        "database:soft_delete",
        f"graph:rebuild:{document.id}",
    ]
    assert repo.get_document(document.id, include_deleted=True).deleted_at is not None  # type: ignore[union-attr]
    assert repo.audit_events[-1]["payload"] == {
        "group_path": "/ops",
        "action_result": "success",
        "qdrant_collection": "documents-test",
        "graphrag_cleanup_status": "complete",
        "graphrag_partition_key": "/ops|clearance:1",
        "graphrag_rebuild_status": "queued",
    }


def test_soft_delete_graph_failure_stops_before_vectors_and_audits() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(
            repo,
            events,
            graph_cleanup=FakeGraphCleanup(events, fail=True),
        ).soft_delete(DeleteDocumentCommand(document_id=document.id, actor=actor))

    assert exc_info.value.code == "document_graphrag_delete_failed"
    assert events == [f"graph:delete:{document.id}"]
    assert repo.get_document(document.id) is not None
    assert repo.audit_events[-1]["payload"]["error_code"] == (
        "document_graphrag_delete_failed"
    )


def test_soft_delete_vector_failure_leaves_document_active_and_audits() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(
            repo,
            events,
            vectors=FakeVectorIndex(events, fail=True),
        ).soft_delete(DeleteDocumentCommand(document_id=document.id, actor=actor))

    assert exc_info.value.code == "document_vectors_delete_failed"
    assert events == [
        f"graph:delete:{document.id}",
        f"vectors:delete:{document.id}",
    ]
    assert repo.get_document(document.id) is not None
    assert repo.audit_events[-1]["payload"]["action_result"] == "failed"


def test_soft_delete_rebuild_failure_is_degraded_not_failed() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)

    result = _service(
        repo,
        events,
        graph_queue=FakeGraphQueue(events, fail=True),
    ).soft_delete(DeleteDocumentCommand(document_id=document.id, actor=actor))

    assert result.status == "soft_deleted"
    assert repo.get_document(document.id, include_deleted=True).deleted_at is not None  # type: ignore[union-attr]
    assert [event["payload"]["action_result"] for event in repo.audit_events] == [
        "warning",
        "success",
    ]
    assert repo.audit_events[-1]["payload"]["graphrag_rebuild_status"] == (
        "enqueue_failed"
    )


def test_permanent_delete_removes_all_assets_before_database_and_rebuild() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("space_admin")
    document = _document(repo, actor=actor)
    _add_image_assets(repo, document.id)

    result = _service(repo, events).permanently_delete(
        DeleteDocumentCommand(document_id=document.id, actor=actor)
    )

    assert result.status == "permanently_deleted"
    assert events == [
        f"graph:delete:{document.id}",
        f"vectors:delete:{document.id}",
        "image:delete:memory://image-page-1.png",
        "image:delete:memory://image-page-2.png",
        "storage:delete:memory://document.pdf",
        "database:permanent_delete",
        f"graph:rebuild:{document.id}",
    ]
    assert repo.get_document(document.id, include_deleted=True) is None
    assert repo.audit_events[-1]["event_type"] == "documents.permanent_delete"
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_permanent_delete_rejects_contributor_before_external_cleanup() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("contributor")
    document = _document(repo, actor=actor)

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(repo, events).permanently_delete(
            DeleteDocumentCommand(document_id=document.id, actor=actor)
        )

    assert exc_info.value.category == "forbidden"
    assert events == []
    assert repo.get_document(document.id) is not None


def test_permanent_delete_shared_document_requires_global_admin() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("space_admin")
    document = _document(repo, actor=actor)
    repo.replace_document_shares(
        document.id,
        group_paths=["/legal"],
        actor_id=actor.id,
    )

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(repo, events).permanently_delete(
            DeleteDocumentCommand(document_id=document.id, actor=actor)
        )

    assert exc_info.value.code == "document_forbidden"
    assert events == []


def test_permanent_delete_vector_failure_stops_before_asset_cleanup() -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("platform_admin")
    document = _document(repo, actor=actor)
    _add_image_assets(repo, document.id)

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(
            repo,
            events,
            vectors=FakeVectorIndex(events, fail=True),
        ).permanently_delete(
            DeleteDocumentCommand(document_id=document.id, actor=actor)
        )

    assert exc_info.value.code == "document_vectors_delete_failed"
    assert events == [
        f"graph:delete:{document.id}",
        f"vectors:delete:{document.id}",
    ]
    assert repo.get_document(document.id, include_deleted=True) is not None
    assert repo.audit_events == []


@pytest.mark.parametrize("failure", ["image", "source"])
def test_permanent_delete_storage_failure_preserves_database_record(
    failure: str,
) -> None:
    events: list[str] = []
    repo = RecordingRepository(events)
    actor = _user("platform_admin")
    document = _document(repo, actor=actor)
    _add_image_assets(repo, document.id)
    image_storage = FakeImageStorage(
        events,
        fail_on="memory://image-page-2.png" if failure == "image" else None,
    )
    storage = FakeStorage(
        events,
        delete_error="object store unavailable" if failure == "source" else None,
    )

    with pytest.raises(DocumentLifecycleRejected) as exc_info:
        _service(
            repo,
            events,
            image_storage=image_storage,
            storage=storage,
        ).permanently_delete(
            DeleteDocumentCommand(document_id=document.id, actor=actor)
        )

    assert exc_info.value.code == "document_file_delete_failed"
    assert events[:4] == [
        f"graph:delete:{document.id}",
        f"vectors:delete:{document.id}",
        "image:delete:memory://image-page-1.png",
        "image:delete:memory://image-page-2.png",
    ]
    assert ("storage:delete:memory://document.pdf" in events) is (
        failure == "source"
    )
    assert "database:permanent_delete" not in events
    assert repo.get_document(document.id, include_deleted=True) is not None
    assert repo.audit_events == []


def _service(
    repo: RecordingRepository,
    events: list[str],
    *,
    storage: FakeStorage | None = None,
    image_storage: FakeImageStorage | None = None,
    ingest_queue: FakeIngestQueue | None = None,
    vectors: FakeVectorIndex | None = None,
    graph_cleanup: FakeGraphCleanup | None = None,
    graph_queue: FakeGraphQueue | None = None,
) -> DocumentLifecycleService:
    return DocumentLifecycleService(
        documents=repo,
        jobs=repo,
        storage=storage or FakeStorage(events),
        image_storage=image_storage or FakeImageStorage(events),
        ingest_queue=ingest_queue or FakeIngestQueue(events),
        vectors=vectors or FakeVectorIndex(events),
        graph_cleanup=graph_cleanup or FakeGraphCleanup(events),
        graph_queue=graph_queue or FakeGraphQueue(events),
        graphrag_enabled=True,
        qdrant_collection="documents-test",
    )


def _user(account_type: str) -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type=account_type,  # type: ignore[arg-type]
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=("/ops",),
    )


def _document(
    repo: InMemoryDocumentRepository,
    *,
    actor: UserRecord,
    file_path: str | None = "memory://document.pdf",
) -> DocumentRecord:
    return repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type="report",
        effective_date=None,
        expiry_date=None,
        description="Lifecycle source",
        uploaded_by=actor.id,
        file_path=file_path,
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="complete",
    )


def _add_image_assets(
    repo: InMemoryDocumentRepository,
    document_id: str,
) -> None:
    repo.replace_document_image_assets(
        doc_id=document_id,
        job_id="job-1",
        assets=[
            {
                "id": "page-2",
                "object_path": "memory://image-page-2.png",
                "content_hash": "hash-2",
                "page": 2,
            },
            {
                "id": "page-1",
                "object_path": "memory://image-page-1.png",
                "content_hash": "hash-1",
                "page": 1,
            },
        ],
    )
