from uuid import uuid4

import pytest

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE
from rag.auth.identity_models import UserRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.graphrag.document_enrichment_service import (
    DocumentGraphEnrichmentRejected,
    DocumentGraphEnrichmentService,
)


class FakeQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[str, str, str, str | None]] = []

    def enqueue(
        self,
        *,
        document_id: str,
        job_id: str,
        reason: str,
        index_generation_id: str | None,
    ) -> None:
        if self.fail:
            raise RuntimeError("broker unavailable")
        self.messages.append(
            (document_id, job_id, reason, index_generation_id)
        )


def test_graph_enrichment_queues_completed_document_and_audits() -> None:
    service, repo, queue, user, document, job = _fixture()

    result = service.enqueue(document.id, actor=user)

    assert result.job_id == job.id
    assert queue.messages == [(document.id, job.id, "user_request", None)]
    assert repo.audit_events[-1]["event_type"] == (
        "documents.graph_enrichment.queued"
    )


def test_graph_enrichment_queue_failure_audits_and_returns_unavailable() -> None:
    service, repo, _, user, document, job = _fixture(queue_fail=True)

    with pytest.raises(DocumentGraphEnrichmentRejected) as exc_info:
        service.enqueue(document.id, actor=user)

    assert exc_info.value.category == "unavailable"
    assert exc_info.value.code == "graphrag_enqueue_failed"
    assert repo.audit_events[-1]["payload"] == {
        "job_id": job.id,
        "error": "broker unavailable",
    }


def test_graph_enrichment_rejects_disabled_workspace_before_queue() -> None:
    service, _, queue, user, document, _ = _fixture(enabled=False)

    with pytest.raises(DocumentGraphEnrichmentRejected) as exc_info:
        service.enqueue(document.id, actor=user)

    assert exc_info.value.code == "graphrag_disabled"
    assert queue.messages == []


def test_graph_enrichment_rejects_abbreviation_glossary() -> None:
    service, _repo, queue, user, document, _ = _fixture(
        doc_type=ABBREVIATION_GLOSSARY_DOC_TYPE
    )

    with pytest.raises(DocumentGraphEnrichmentRejected) as exc_info:
        service.enqueue(document.id, actor=user)

    assert exc_info.value.code == "document_not_graph_eligible"
    assert queue.messages == []


def _fixture(
    *,
    enabled: bool = True,
    queue_fail: bool = False,
    doc_type: str | None = None,
):
    repo = InMemoryDocumentRepository()
    user = _user()
    document = repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type=doc_type,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=user.id,
        file_path="memory://document.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="complete",
    )
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="complete",
        progress_pct=100,
        origin="upload",
    )
    queue = FakeQueue(fail=queue_fail)
    service = DocumentGraphEnrichmentService(
        document_repo=repo,
        job_repo=repo,
        queue=queue,
        enrichment_enabled=lambda: enabled,
    )
    return service, repo, queue, user, document, job


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
