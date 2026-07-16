from __future__ import annotations

from uuid import uuid4

import pytest

from rag.auth.identity_models import UserRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.ingestion.cancellation import (
    CancelIngestJob,
    DocumentVectorCleanupError,
    IngestCancellationError,
)


class RecordingQueue:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)


class RecordingVectorCleaner:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_building_vectors(self, job_id: str) -> None:
        self.deleted.append(job_id)


def test_cancellation_orders_state_revoke_vectors_then_audit() -> None:
    repo = _OrderedRepository()
    user = _user("contributor")
    document = _document(repo, user=user, status="processing")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="processing",
        progress_pct=42,
        origin="upload",
    )
    queue = _OrderedQueue(repo, job.id)
    cleaner = _OrderedVectorCleaner(repo, job.id)

    result = _service(repo, queue=queue, cleaner=cleaner).execute(
        job_id=job.id,
        actor=user,
    )

    assert result.status == "cancelled"
    assert repo.operations == ["state", "revoke", "vectors", "audit"]
    assert repo.audit_events[-1]["payload"] == {
        "doc_id": document.id,
        "status_before": "processing",
        "progress_pct": 42,
        "review_items_closed": 0,
        "revoke_error": None,
        "vector_cleanup_error": None,
    }


def test_cancellation_records_best_effort_cleanup_failures() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user, status="queued")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="queued",
        progress_pct=0,
        origin="upload",
    )

    result = _service(
        repo,
        queue=_FailingQueue(),
        cleaner=_FailingVectorCleaner(),
    ).execute(job_id=job.id, actor=user)

    assert result.status == "cancelled"
    assert repo.audit_events[-1]["payload"]["revoke_error"] == "broker unavailable"
    assert (
        repo.audit_events[-1]["payload"]["vector_cleanup_error"]
        == "qdrant unavailable"
    )


def test_cancellation_rejects_unknown_job_without_side_effects() -> None:
    repo = InMemoryDocumentRepository()
    queue = RecordingQueue()
    cleaner = RecordingVectorCleaner()

    with pytest.raises(IngestCancellationError) as raised:
        _service(repo, queue=queue, cleaner=cleaner).execute(
            job_id="missing-job",
            actor=_user("contributor"),
        )

    assert raised.value.code == "job_not_found"
    assert raised.value.category == "not_found"
    assert queue.cancelled == []
    assert cleaner.deleted == []
    assert repo.audit_events == []


def test_cancellation_reports_missing_document_without_cleanup() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user, status="queued")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="queued",
        progress_pct=0,
        origin="upload",
    )
    del repo._documents[document.id]
    queue = RecordingQueue()
    cleaner = RecordingVectorCleaner()

    with pytest.raises(IngestCancellationError) as raised:
        _service(repo, queue=queue, cleaner=cleaner).execute(
            job_id=job.id,
            actor=user,
        )

    assert raised.value.code == "document_not_found"
    assert raised.value.category == "not_found"
    assert queue.cancelled == []
    assert cleaner.deleted == []
    assert repo.audit_events == []


def test_cancellation_rejects_user_without_document_write_scope() -> None:
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor")
    document = _document(repo, user=uploader, status="queued")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="queued",
        progress_pct=0,
        origin="upload",
    )

    with pytest.raises(IngestCancellationError) as raised:
        _service(repo).execute(job_id=job.id, actor=_user("member"))

    assert raised.value.code == "ingest_cancel_forbidden"
    assert raised.value.category == "forbidden"
    assert repo.get_ingest_job(job.id).status == "queued"  # type: ignore[union-attr]


def test_terminal_job_is_idempotent_without_cleanup_or_audit() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user, status="complete")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="complete",
        progress_pct=100,
        origin="upload",
    )
    queue = RecordingQueue()
    cleaner = RecordingVectorCleaner()

    result = _service(repo, queue=queue, cleaner=cleaner).execute(
        job_id=job.id,
        actor=user,
    )

    assert result.status == "complete"
    assert result.message == "Job is already complete."
    assert queue.cancelled == []
    assert cleaner.deleted == []
    assert repo.audit_events == []


class _OrderedRepository(InMemoryDocumentRepository):
    def __init__(self) -> None:
        super().__init__()
        self.operations: list[str] = []

    def cancel_ingest_job(self, job_id: str, *, allowed_statuses: frozenset[str]):
        result = super().cancel_ingest_job(
            job_id,
            allowed_statuses=allowed_statuses,
        )
        self.operations.append("state")
        return result

    def append_audit_event(self, **kwargs: object) -> None:
        self.operations.append("audit")
        super().append_audit_event(**kwargs)  # type: ignore[arg-type]


class _OrderedQueue:
    def __init__(self, repo: _OrderedRepository, job_id: str) -> None:
        self._repo = repo
        self._job_id = job_id

    def cancel(self, job_id: str) -> None:
        assert job_id == self._job_id
        assert self._repo.get_ingest_job(job_id).status == "cancelled"  # type: ignore[union-attr]
        self._repo.operations.append("revoke")


class _OrderedVectorCleaner:
    def __init__(self, repo: _OrderedRepository, job_id: str) -> None:
        self._repo = repo
        self._job_id = job_id

    def delete_building_vectors(self, job_id: str) -> None:
        assert job_id == self._job_id
        assert self._repo.get_ingest_job(job_id).status == "cancelled"  # type: ignore[union-attr]
        self._repo.operations.append("vectors")


class _FailingQueue:
    def cancel(self, job_id: str) -> None:
        _ = job_id
        raise RuntimeError("broker unavailable")


class _FailingVectorCleaner:
    def delete_building_vectors(self, job_id: str) -> None:
        _ = job_id
        raise DocumentVectorCleanupError("qdrant unavailable")


def _service(
    repo: InMemoryDocumentRepository,
    *,
    queue: object | None = None,
    cleaner: object | None = None,
) -> CancelIngestJob:
    return CancelIngestJob(
        document_repo=repo,
        job_repo=repo,
        queue=queue or RecordingQueue(),  # type: ignore[arg-type]
        vector_cleaner=cleaner or RecordingVectorCleaner(),  # type: ignore[arg-type]
    )


def _document(
    repo: InMemoryDocumentRepository,
    *,
    user: UserRecord,
    status: str,
):
    return repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=user.id,
        file_path="memory://document.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status=status,
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
