from __future__ import annotations

from uuid import uuid4

import pytest

from rag.documents.upload_service import (
    UploadDocument,
    UploadDocumentCommand,
    UploadDocumentResult,
    UploadRejected,
)
from rag.ingestion.contracts import IngestJobPayload
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.repositories.ingest_job_models import IngestJobRepository
from rag.repositories.identity import InMemoryIdentityRepository, UserRecord
from rag.services.file_scanning import NoopFileScanner
from rag.services.upload_storage import StoredUpload


class FakeQueue:
    def __init__(self) -> None:
        self.messages: list[IngestJobPayload] = []

    def enqueue(self, message: IngestJobPayload) -> None:
        self.messages.append(message)


class FakeStorage:
    def put(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> StoredUpload:
        return StoredUpload(
            object_path=f"memory://{filename}",
            size_bytes=len(content),
            content_type=content_type,
        )


def test_upload_can_share_document_with_multiple_spaces_as_global_admin() -> None:
    document_repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance", "/ops")
    admin = _user("platform_admin", group_paths=())
    queue = FakeQueue()

    response = _upload(
        group_path="/legal",
        shared_group_paths=["/finance", "/ops"],
        user=admin,
        document_repo=document_repo,
        identity_repo=identity_repo,
        queue=queue,
    )

    job_repo: IngestJobRepository = document_repo
    job = job_repo.get_ingest_job(response.job_id)
    document = document_repo.get_document(job.doc_id) if job else None
    assert document is not None
    assert document.owner_group_path == "/legal"
    assert list(document.shared_group_paths) == ["/finance", "/ops"]
    assert queue.messages[0].group_path == "/legal"
    assert queue.messages[0].acl_group_paths == ["/legal", "/finance", "/ops"]
    assert document_repo.audit_events[-1]["payload"]["shared_group_paths"] == [
        "/finance",
        "/ops",
    ]


def test_space_admin_can_share_upload_only_with_managed_spaces() -> None:
    document_repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance")
    admin = _user("space_admin", group_paths=("/legal", "/finance"))
    queue = FakeQueue()

    response = _upload(
        group_path="/legal",
        shared_group_paths=["/finance"],
        user=admin,
        document_repo=document_repo,
        identity_repo=identity_repo,
        queue=queue,
    )

    job_repo: IngestJobRepository = document_repo
    job = job_repo.get_ingest_job(response.job_id)
    document = document_repo.get_document(job.doc_id) if job else None
    assert document is not None
    assert list(document.shared_group_paths) == ["/finance"]
    assert queue.messages[0].acl_group_paths == ["/legal", "/finance"]


def test_contributor_cannot_share_upload_across_spaces() -> None:
    document_repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal", "/finance")
    contributor = _user("contributor", group_paths=("/legal",))

    with pytest.raises(UploadRejected) as exc_info:
        _upload(
            group_path="/legal",
            shared_group_paths=["/finance"],
            user=contributor,
            document_repo=document_repo,
            identity_repo=identity_repo,
            queue=FakeQueue(),
        )

    assert exc_info.value.category == "forbidden"
    assert exc_info.value.code == "upload_share_forbidden"
    assert document_repo.list_documents() == []


def test_upload_rejects_missing_shared_space() -> None:
    document_repo = InMemoryDocumentRepository()
    identity_repo = _identity_repo("/legal")
    admin = _user("platform_admin", group_paths=())

    with pytest.raises(UploadRejected) as exc_info:
        _upload(
            group_path="/legal",
            shared_group_paths=["/finance"],
            user=admin,
            document_repo=document_repo,
            identity_repo=identity_repo,
            queue=FakeQueue(),
        )

    assert exc_info.value.category == "invalid"
    assert exc_info.value.code == "group_not_found"
    assert document_repo.list_documents() == []


def _upload(
    *,
    group_path: str,
    shared_group_paths: list[str],
    user: UserRecord,
    document_repo: InMemoryDocumentRepository,
    identity_repo: InMemoryIdentityRepository,
    queue: FakeQueue,
) -> UploadDocumentResult:
    service = UploadDocument(
        identity_repo=identity_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        storage=FakeStorage(),  # type: ignore[arg-type]
        scanner=NoopFileScanner(),
        queue=queue,
        max_upload_bytes=1024 * 1024,
    )
    return service.execute(
        UploadDocumentCommand(
            actor=user,
            content=b"%PDF-1.7\nshared spaces\n%%EOF",
            filename=f"{uuid4()}.pdf",
            declared_content_type="application/pdf",
            group_path=group_path,
            clearance_level="NATO_RESTRICTED",
            effective_date=None,
            expiry_date=None,
            doc_type=None,
            description=None,
            quality_preset=None,
            supersedes=(),
            shared_group_paths=tuple(shared_group_paths),
        )
    )


def _identity_repo(*group_paths: str) -> InMemoryIdentityRepository:
    repo = InMemoryIdentityRepository()
    for path in group_paths:
        repo.create_group(path=path, name=path.removeprefix("/").title())
    return repo


def _user(account_type: str, *, group_paths: tuple[str, ...]) -> UserRecord:
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
        group_paths=group_paths,
    )
