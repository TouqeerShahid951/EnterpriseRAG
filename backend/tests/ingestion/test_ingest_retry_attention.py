from __future__ import annotations

import asyncio

from rag.api.routes.ingest_job_routes import summarize_ingest_jobs
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.auth.identity_models import UserRecord


def test_retry_job_keeps_failed_history_but_links_new_job() -> None:
    repo = InMemoryDocumentRepository()
    document = _document(repo)
    failed = repo.create_ingest_job(doc_id=document.id, status="failed", progress_pct=100, origin="upload")
    retry = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="reingest", retry_of_job_id=failed.id)

    assert retry.id != failed.id
    assert retry.retry_of_job_id == failed.id
    assert repo.get_ingest_job(failed.id).status == "failed"


def test_latest_failed_job_counts_as_attention() -> None:
    repo = InMemoryDocumentRepository()
    document = _document(repo)
    repo.create_ingest_job(doc_id=document.id, status="failed", progress_pct=100, origin="upload")

    summary = _summary(repo)

    assert summary.status_counts["failed"] == 1
    assert summary.needs_attention == 1


def test_successful_retry_clears_attention_without_erasing_failed_history() -> None:
    repo = InMemoryDocumentRepository()
    document = _document(repo)
    failed = repo.create_ingest_job(doc_id=document.id, status="failed", progress_pct=100, origin="upload")
    retry = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="reingest", retry_of_job_id=failed.id)

    queued_summary = _summary(repo)
    assert queued_summary.status_counts["failed"] == 1
    assert queued_summary.needs_attention == 1

    repo.update_ingest_job(retry.id, status="complete", progress_pct=100)
    complete_summary = _summary(repo)

    assert complete_summary.status_counts["failed"] == 1
    assert complete_summary.needs_attention == 0


def _summary(repo: InMemoryDocumentRepository):
    return asyncio.run(
        summarize_ingest_jobs(
            group_path=None,
            created_from=None,
            created_to=None,
            user=_user(),
            job_repo=repo,
        )
    )


def _document(repo: InMemoryDocumentRepository):
    return repo.create_document(
        title="Source.pdf",
        source_id="source-1",
        group_path="/space",
        clearance_level="NATO_RESTRICTED",
        doc_type="pdf",
        effective_date=None,
        expiry_date=None,
        pending_supersedes=[],
        content_hash="hash-1",
        uploaded_by="user-1",
        file_path="source.pdf",
        ingest_status="queued",
    )


def _user() -> UserRecord:
    return UserRecord(
        id="user-1",
        email="user@example.test",
        name="User",
        password_hash="hash",
        is_active=True,
        account_type="contributor",
        clearance_level="NATO_SECRET",
        must_change_password=False,
        permission_version=1,
        group_paths=("/space",),
    )
