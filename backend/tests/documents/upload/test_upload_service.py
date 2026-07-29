from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE
from rag.documents.upload.service import (
    UploadDocument,
    UploadDocumentCommand,
    UploadRejected,
)
from rag.documents.adapters.file_scanning import NoopFileScanner
from rag.documents.scanning import MalwareDetectedError, ScannerUnavailableError
from rag.documents.storage import StoredUpload
from rag.ingestion.contracts import IngestJobPayload
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.auth.adapters.identity_memory import InMemoryIdentityRepository
from rag.auth.identity_models import UserRecord

PDF_CONTENT = b"%PDF-1.7\nservice upload\n%%EOF"


class FakeQueue:
    def __init__(self, *, error: str | None = None) -> None:
        self.error = error
        self.messages: list[IngestJobPayload] = []

    def enqueue(self, message: IngestJobPayload) -> None:
        if self.error:
            raise RuntimeError(self.error)
        self.messages.append(message)


class FakeStorage:
    def __init__(self, *, error: str | None = None) -> None:
        self.error = error
        self.puts: list[tuple[str, bytes, str | None]] = []

    def put(
        self, *, filename: str, content: bytes, content_type: str | None
    ) -> StoredUpload:
        if self.error:
            raise RuntimeError(self.error)
        self.puts.append((filename, content, content_type))
        return StoredUpload(
            object_path=f"memory://{filename}",
            size_bytes=len(content),
            content_type=content_type,
        )


class RejectingScanner:
    def __init__(self, error: RuntimeError) -> None:
        self.error = error

    def scan(self, content: bytes) -> None:
        _ = content
        raise self.error


def test_upload_service_persists_audits_and_dispatches_normalized_upload() -> None:
    document_repo, identity_repo, user = _context()
    queue = FakeQueue()
    storage = FakeStorage()
    service = _service(document_repo, identity_repo, queue=queue, storage=storage)

    result = service.execute(
        replace(
            _command(user),
            description="  Source document  ",
            doc_type="  Legal   Brief  ",
            quality_preset="HIGH_ACCURACY",
        )
    )

    job = document_repo.get_ingest_job(result.job_id)
    document = document_repo.get_document(job.doc_id) if job else None
    assert job is not None
    assert job.status == "queued"
    assert job.origin == "upload"
    assert document is not None
    assert document.description == "Source document"
    assert document.doc_type == "legal brief"
    assert storage.puts == [("contract.pdf", PDF_CONTENT, "application/pdf")]
    assert len(queue.messages) == 1
    assert queue.messages[0].delivery_id is not None
    assert replace(queue.messages[0], delivery_id=None) == IngestJobPayload(
            job_id=job.id,
            doc_id=document.id,
            file_path="memory://contract.pdf",
            group_path="/legal",
            acl_group_paths=["/legal"],
            clearance_level="NATO_RESTRICTED",
            doc_type="legal brief",
            effective_date=None,
            supersedes=[],
            expiry_date=None,
            description="Source document",
            content_type="application/pdf",
            quality_preset="high_accuracy",
        )
    assert document_repo.audit_events[-1]["event_type"] == "upload.queued"
    assert (
        document_repo.audit_events[-1]["payload"]["quality_preset"] == "high_accuracy"
    )


@pytest.mark.parametrize(
    ("changes", "category", "code"),
    [
        ({"content": b""}, "invalid", "empty_upload"),
        ({"content": b"plain text"}, "invalid", "unsupported_file_type"),
        ({"description": "x" * 2001}, "invalid", "invalid_description"),
        ({"quality_preset": "slow"}, "invalid", "invalid_quality_preset"),
        (
            {
                "effective_date": date.today(),
                "expiry_date": date.today() - timedelta(days=1),
            },
            "invalid",
            "invalid_expiry_date",
        ),
        ({"clearance_level": "NATO_SECRET"}, "forbidden", "upload_clearance_forbidden"),
    ],
)
def test_upload_service_rejects_invalid_commands_before_side_effects(
    changes: dict[str, object],
    category: str,
    code: str,
) -> None:
    document_repo, identity_repo, user = _context()
    queue = FakeQueue()
    storage = FakeStorage()
    service = _service(document_repo, identity_repo, queue=queue, storage=storage)

    with pytest.raises(UploadRejected) as exc_info:
        service.execute(replace(_command(user), **changes))

    assert exc_info.value.category == category
    assert exc_info.value.code == code
    assert document_repo.list_documents() == []
    assert document_repo.list_ingest_jobs() == []
    assert storage.puts == []
    assert queue.messages == []


def test_upload_service_rejects_oversized_file_before_side_effects() -> None:
    document_repo, identity_repo, user = _context()
    queue = FakeQueue()
    storage = FakeStorage()
    service = _service(
        document_repo,
        identity_repo,
        queue=queue,
        storage=storage,
        max_upload_bytes=8,
    )

    with pytest.raises(UploadRejected) as exc_info:
        service.execute(_command(user))

    assert exc_info.value.category == "too_large"
    assert exc_info.value.code == "upload_too_large"
    assert (
        exc_info.value.message == "Uploaded file exceeds the 7.62939e-06 MB size limit."
    )
    assert document_repo.list_documents() == []
    assert storage.puts == []
    assert queue.messages == []


def test_upload_service_rejects_duplicate_before_scanning_or_storage() -> None:
    document_repo, identity_repo, user = _context()
    queue = FakeQueue()
    storage = FakeStorage()
    service = _service(document_repo, identity_repo, queue=queue, storage=storage)
    service.execute(_command(user))

    with pytest.raises(UploadRejected) as exc_info:
        service.execute(replace(_command(user), filename="duplicate.pdf"))

    assert exc_info.value.category == "conflict"
    assert exc_info.value.code == "duplicate_document"
    assert len(document_repo.list_documents()) == 1
    assert len(storage.puts) == 1
    assert len(queue.messages) == 1


@pytest.mark.parametrize(
    ("scanner_error", "category", "code", "message"),
    [
        (
            MalwareDetectedError("Eicar-Test-Signature FOUND"),
            "invalid",
            "malware_detected",
            "Upload failed virus scanning.",
        ),
        (
            ScannerUnavailableError("connection refused"),
            "unavailable",
            "scanner_unavailable",
            "File scanner unavailable: connection refused",
        ),
    ],
)
def test_upload_service_maps_scanner_failures_without_persisting(
    scanner_error: RuntimeError,
    category: str,
    code: str,
    message: str,
) -> None:
    document_repo, identity_repo, user = _context()
    storage = FakeStorage()
    service = _service(
        document_repo,
        identity_repo,
        queue=FakeQueue(),
        storage=storage,
        scanner=RejectingScanner(scanner_error),
    )

    with pytest.raises(UploadRejected) as exc_info:
        service.execute(_command(user))

    assert exc_info.value.category == category
    assert exc_info.value.code == code
    assert exc_info.value.message == message
    assert document_repo.list_documents() == []
    assert storage.puts == []


def test_upload_service_preserves_storage_failure_as_unexpected_error() -> None:
    document_repo, identity_repo, user = _context()
    service = _service(
        document_repo,
        identity_repo,
        queue=FakeQueue(),
        storage=FakeStorage(error="object storage unavailable"),
    )

    with pytest.raises(RuntimeError, match="object storage unavailable"):
        service.execute(_command(user))

    assert document_repo.list_documents() == []
    assert document_repo.list_ingest_jobs() == []


def test_upload_service_keeps_queued_job_when_queue_is_unavailable() -> None:
    document_repo, identity_repo, user = _context()
    queue = FakeQueue(error="redis connection refused")
    service = _service(
        document_repo,
        identity_repo,
        queue=queue,
        storage=FakeStorage(),
    )

    result = service.execute(_command(user))

    jobs = document_repo.list_ingest_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == result.job_id
    assert jobs[0].status == "queued"
    assert jobs[0].error_code is None
    assert jobs[0].delivery_count == 1
    assert jobs[0].failure_attempt_count == 0
    assert jobs[0].active_delivery_id is not None
    assert queue.messages == []
    assert len(document_repo.list_documents()) == 1
    assert document_repo.audit_events[-1]["event_type"] == "upload.queued"


def test_abbreviation_glossary_upload_requires_an_admin_and_a_pdf() -> None:
    document_repo, identity_repo, contributor = _context()
    service = _service(
        document_repo,
        identity_repo,
        queue=FakeQueue(),
        storage=FakeStorage(),
    )
    glossary_command = replace(
        _command(contributor),
        doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        clearance_level="NATO_UNCLASSIFIED",
    )

    with pytest.raises(UploadRejected) as exc_info:
        service.execute(glossary_command)
    assert exc_info.value.code == "abbreviation_glossary_admin_required"

    admin = replace(contributor, account_type="system_admin")
    with pytest.raises(UploadRejected) as exc_info:
        service.execute(
            replace(glossary_command, actor=admin, shared_group_paths=("/ops",))
        )
    assert exc_info.value.code == "abbreviation_glossary_scope_not_allowed"

    with pytest.raises(UploadRejected) as exc_info:
        service.execute(
            replace(
                glossary_command,
                actor=admin,
                content=b"{}",
                filename="glossary.json",
                declared_content_type="application/json",
            )
        )
    assert exc_info.value.code == "abbreviation_glossary_pdf_required"


def test_abbreviation_glossary_can_add_or_replace_one_pdf_source() -> None:
    document_repo, identity_repo, contributor = _context()
    admin = replace(contributor, account_type="system_admin")
    current = document_repo.create_document(
        title="Current glossary.pdf",
        source_id="upload:current-glossary",
        group_path="/legal",
        clearance_level="NATO_RESTRICTED",
        doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=admin.id,
        file_path="memory://current-glossary.pdf",
        content_hash="current-glossary-hash",
        pending_supersedes=[],
        ingest_status="complete",
    )
    queue = FakeQueue()
    service = _service(
        document_repo,
        identity_repo,
        queue=queue,
        storage=FakeStorage(),
    )
    command = replace(
        _command(admin),
        doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE,
        clearance_level="NATO_UNCLASSIFIED",
    )

    added = service.execute(command)
    added_job = document_repo.get_ingest_job(added.job_id)
    assert added_job is not None
    assert queue.messages[0].supersedes == []

    result = service.execute(
        replace(
            command,
            content=b"%PDF-1.7\nreplacement glossary\n%%EOF",
            filename="replacement-glossary.pdf",
            supersedes=(current.id,),
        )
    )

    job = document_repo.get_ingest_job(result.job_id)
    assert job is not None
    assert queue.messages[1].doc_type == ABBREVIATION_GLOSSARY_DOC_TYPE
    assert queue.messages[1].supersedes == [current.id]


def _service(
    document_repo: InMemoryDocumentRepository,
    identity_repo: InMemoryIdentityRepository,
    *,
    queue: FakeQueue,
    storage: FakeStorage,
    scanner: object | None = None,
    max_upload_bytes: int = 1024 * 1024,
) -> UploadDocument:
    return UploadDocument(
        identity_repo=identity_repo,
        document_repo=document_repo,
        job_repo=document_repo,
        storage=storage,  # type: ignore[arg-type]
        scanner=scanner or NoopFileScanner(),  # type: ignore[arg-type]
        queue=queue,
        max_upload_bytes=max_upload_bytes,
    )


def _context() -> tuple[
    InMemoryDocumentRepository, InMemoryIdentityRepository, UserRecord
]:
    document_repo = InMemoryDocumentRepository()
    identity_repo = InMemoryIdentityRepository()
    identity_repo.create_group(path="/legal", name="Legal")
    user = UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Test User",
        password_hash="hash",
        is_active=True,
        account_type="contributor",
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=("/legal",),
    )
    return document_repo, identity_repo, user


def _command(user: UserRecord) -> UploadDocumentCommand:
    return UploadDocumentCommand(
        actor=user,
        content=PDF_CONTENT,
        filename="contract.pdf",
        declared_content_type="application/pdf",
        group_path="/legal",
        clearance_level="NATO_RESTRICTED",
        effective_date=None,
        expiry_date=None,
        doc_type=None,
        description=None,
        quality_preset=None,
        supersedes=(),
        shared_group_paths=(),
    )
