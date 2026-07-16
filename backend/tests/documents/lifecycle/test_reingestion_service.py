from uuid import uuid4

import pytest

from rag.auth.identity_models import UserRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.lifecycle.reingestion_service import (
    DocumentReingestionRejected,
    DocumentReingestionService,
)
from rag.documents.storage import StoredUploadContent


class FakeStorage:
    def read(self, _object_path: str) -> StoredUploadContent:
        return StoredUploadContent(
            content=b"source",
            content_type="application/pdf",
            filename="source.pdf",
        )


class FakeQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages = []

    def enqueue(self, message) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.messages.append(message)


def test_reingest_creates_payload_and_audits_success() -> None:
    service, repo, queue, user, document = _fixture()

    result = service.reingest(
        document.id,
        actor=user,
        retry_of_job_id=None,
    )

    assert result.document_id == document.id
    assert queue.messages[0].job_id == result.job_id
    assert queue.messages[0].file_path == document.file_path
    assert queue.messages[0].acl_group_paths == ["/ops"]
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_reingest_queue_failure_keeps_durable_queued_job() -> None:
    service, repo, _, user, document = _fixture(queue_fail=True)

    result = service.reingest(
        document.id,
        actor=user,
        retry_of_job_id=None,
    )

    job = repo.list_ingest_jobs()[0]
    assert job.id == result.job_id
    assert job.status == "queued"
    assert job.failure_attempt_count == 0
    assert job.active_delivery_id is not None
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_reingest_rejects_active_job_before_source_or_new_job() -> None:
    service, repo, _, user, document = _fixture()
    existing = repo.create_ingest_job(
        doc_id=document.id,
        status="queued",
        progress_pct=0,
        origin="reingest",
    )

    with pytest.raises(DocumentReingestionRejected) as exc_info:
        service.reingest(
            document.id,
            actor=user,
            retry_of_job_id=None,
        )

    assert exc_info.value.code == "document_ingest_active"
    assert [job.id for job in repo.list_ingest_jobs()] == [existing.id]


def test_reingest_links_failed_retry_job() -> None:
    service, repo, queue, user, document = _fixture()
    retry = repo.create_ingest_job(
        doc_id=document.id,
        status="failed",
        progress_pct=0,
        origin="reingest",
    )

    result = service.reingest(
        document.id,
        actor=user,
        retry_of_job_id=retry.id,
    )

    created = repo.get_ingest_job(result.job_id)
    assert created is not None and created.retry_of_job_id == retry.id
    assert queue.messages[0].job_id == created.id


def _fixture(*, queue_fail: bool = False):
    repo = InMemoryDocumentRepository()
    user = _user()
    document = repo.create_document(
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
        ingest_status="complete",
    )
    queue = FakeQueue(fail=queue_fail)
    service = DocumentReingestionService(
        document_repo=repo,
        job_repo=repo,
        storage=FakeStorage(),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
    )
    return service, repo, queue, user, document


def _user() -> UserRecord:
    user_id = str(uuid4())
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.test",
        name="Uploader",
        password_hash="hash",
        is_active=True,
        account_type="contributor",
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=("/ops",),
    )
