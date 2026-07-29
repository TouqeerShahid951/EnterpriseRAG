from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from rag.auth.identity_models import UserRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.overview import build_document_overview
from rag.documents.routes.presenters import document_overview_to_schema


def test_document_overview_counts_visible_current_documents_once() -> None:
    repo = InMemoryDocumentRepository()
    user = _user()
    today = date(2026, 7, 18)
    _document(repo, user, status="complete", expiry_date=today + timedelta(days=10))
    failed = _document(repo, user, status="failed")
    review = _document(repo, user, status="human_review")
    _document(repo, user, status="processing")
    _document(repo, user, status="cancelled")
    unknown = _document(repo, user, status="unknown")
    old = _document(repo, user, status="failed")
    replacement = _document(repo, user, status="complete")
    repo.mark_superseded(new_doc_id=replacement.id, old_doc_ids=[old.id])
    shared = _document(repo, user, status="failed", group_path="/finance")
    repo.replace_document_shares(shared.id, group_paths=["/ops"], actor_id=user.id)
    deleted = _document(repo, user, status="failed")
    repo.soft_delete_document(deleted.id)
    _document(repo, user, status="failed", group_path="/hidden")
    _document(
        repo,
        user,
        status="failed",
        clearance_level="NATO_CONFIDENTIAL",
    )

    overview = build_document_overview(user=user, repository=repo, today=today)

    assert overview.library_documents == 9
    assert overview.current_versions == 8
    assert overview.indexed_current == 2
    assert overview.processing_current == 1
    assert overview.review_current == 1
    assert overview.failed_current == 2
    assert overview.unknown_current == 1
    assert overview.needs_attention == 4
    assert overview.superseded_versions == 1
    assert overview.expiring_soon_current == 1
    assert overview.trash == 1
    assert {document.id for document in overview.attention_documents} == {
        failed.id,
        review.id,
        shared.id,
        unknown.id,
    }
    assert {space.group_path for space in overview.spaces} == {"/ops"}
    assert overview.spaces[0].library_documents == 9
    assert document_overview_to_schema(overview).unknown_current == 1


def test_retry_replaces_failure_attention_instead_of_stacking_it() -> None:
    repo = InMemoryDocumentRepository()
    user = _user()
    document = _document(repo, user, status="failed")
    failed_job = repo.create_ingest_job(
        doc_id=document.id,
        status="failed",
        progress_pct=35,
        origin="upload",
    )

    assert build_document_overview(user=user, repository=repo).needs_attention == 1

    retry = repo.create_ingest_job(
        doc_id=document.id,
        retry_of_job_id=failed_job.id,
        status="queued",
        progress_pct=0,
        origin="reingest",
    )
    processing = build_document_overview(user=user, repository=repo)
    assert processing.needs_attention == 0
    assert processing.processing_current == 1

    repo.update_ingest_job(retry.id, status="failed", progress_pct=35)
    failed_again = build_document_overview(user=user, repository=repo)
    assert failed_again.needs_attention == 1
    assert failed_again.failed_current == 1

    _document(repo, user, status="processing")
    unrelated = build_document_overview(user=user, repository=repo)
    assert unrelated.needs_attention == 1
    assert unrelated.processing_current == 1


def _document(
    repo: InMemoryDocumentRepository,
    user: UserRecord,
    *,
    status: str,
    group_path: str = "/ops",
    clearance_level: str = "NATO_RESTRICTED",
    expiry_date: date | None = None,
):
    return repo.create_document(
        title=f"{status}-{uuid4()}.pdf",
        source_id=f"upload:{uuid4()}",
        group_path=group_path,
        clearance_level=clearance_level,
        doc_type=None,
        effective_date=None,
        expiry_date=expiry_date,
        description=None,
        uploaded_by=user.id,
        file_path="memory://document.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status=status,
    )


def _user() -> UserRecord:
    return UserRecord(
        id=str(uuid4()),
        email=f"{uuid4()}@example.test",
        name="Reviewer",
        password_hash="hash",
        is_active=True,
        account_type="contributor",
        clearance_level="NATO_RESTRICTED",
        must_change_password=False,
        permission_version=1,
        group_paths=("/ops",),
    )
