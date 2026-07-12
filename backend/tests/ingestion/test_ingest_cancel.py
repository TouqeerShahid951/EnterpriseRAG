from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from rag.api.routes import ingest_job_routes
from rag.core.config import settings
from rag.internal.ingest_status_routes import update_ingest_job_status
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.auth.identity_models import UserRecord
from rag.schemas.internal import InternalJobStatusRequest, ServiceTokenContext


class FakeQueue:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)


def test_cancel_active_ingest_job_marks_cancelled_and_cleans_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="processing")
    job = repo.create_ingest_job(doc_id=document.id, status="processing", progress_pct=34, origin="upload")
    queue = FakeQueue()
    deleted_docs: list[str] = []
    monkeypatch.setattr(ingest_job_routes, "_delete_document_vectors", lambda doc_id: deleted_docs.append(doc_id) or None)

    response = _cancel(repo, job.id, user=user, queue=queue)

    updated = repo.get_ingest_job(job.id)
    assert response.status == "cancelled"
    assert updated is not None
    assert updated.status == "cancelled"
    assert updated.progress_pct == 34
    assert updated.completed_at is not None
    assert repo.get_document(document.id).ingest_status == "cancelled"  # type: ignore[union-attr]
    assert queue.cancelled == [job.id]
    assert deleted_docs == [document.id]
    assert repo.audit_events[-1]["event_type"] == "ingest.cancelled"


def test_cancel_human_review_job_closes_pending_review_items(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="human_review")
    job = repo.create_ingest_job(doc_id=document.id, status="human_review", progress_pct=35, origin="upload")
    repo.create_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id, "file_path": "memory://doc", "group_path": "/ops"},
        review_items=[{"item_index": 0, "partial_text": "uncertain", "confidence": 0.4}],
    )
    monkeypatch.setattr(ingest_job_routes, "_delete_document_vectors", lambda _doc_id: None)

    _cancel(repo, job.id, user=user, queue=FakeQueue())

    assert repo.get_ingest_job(job.id).status == "cancelled"  # type: ignore[union-attr]
    assert repo.list_review_items(status="pending") == []
    assert len(repo.list_review_items(status="rejected")) == 1


def test_cancel_image_review_job_closes_pending_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="human_review")
    job = repo.create_ingest_job(doc_id=document.id, status="human_review", progress_pct=35, origin="upload")
    batch = repo.create_image_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id},
        candidates=[
            {
                "candidate_key": "page-1",
                "object_path": "memory://page-1.png",
                "content_hash": "hash-1",
            }
        ],
    )
    monkeypatch.setattr(ingest_job_routes, "_delete_document_vectors", lambda _doc_id: None)

    _cancel(repo, job.id, user=user, queue=FakeQueue())

    assert repo.get_ingest_job(job.id).status == "cancelled"  # type: ignore[union-attr]
    assert repo.get_image_review_batch(batch.id).status == "rejected"  # type: ignore[union-attr]
    candidates = repo.list_image_review_candidates_for_batch(batch.id)
    assert [candidate.status for candidate in candidates] == ["skipped"]
    assert [candidate.skip_reason for candidate in candidates] == ["ingest_cancelled"]


def test_cancel_ingest_job_requires_write_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor", group_paths=("/ops",))
    reader = _user("member", group_paths=("/ops",))
    document = _document(repo, user=uploader, status="queued")
    job = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="upload")
    monkeypatch.setattr(ingest_job_routes, "_delete_document_vectors", lambda _doc_id: None)

    with pytest.raises(HTTPException) as exc_info:
        _cancel(repo, job.id, user=reader, queue=FakeQueue())

    assert exc_info.value.status_code == 403
    assert repo.get_ingest_job(job.id).status == "queued"  # type: ignore[union-attr]


def test_cancel_ingest_job_rejects_same_space_peer_contributor(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor", group_paths=("/ops",))
    peer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=uploader, status="queued")
    job = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="upload")
    monkeypatch.setattr(ingest_job_routes, "_delete_document_vectors", lambda _doc_id: None)

    with pytest.raises(HTTPException) as exc_info:
        _cancel(repo, job.id, user=peer, queue=FakeQueue())

    assert exc_info.value.status_code == 403
    assert repo.get_ingest_job(job.id).status == "queued"  # type: ignore[union-attr]


def test_cancel_ingest_job_allows_space_admin_in_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor", group_paths=("/ops",))
    space_admin = _user("space_admin", group_paths=("/ops",))
    document = _document(repo, user=uploader, status="queued")
    job = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="upload")
    queue = FakeQueue()
    monkeypatch.setattr(ingest_job_routes, "_delete_document_vectors", lambda _doc_id: None)

    response = _cancel(repo, job.id, user=space_admin, queue=queue)

    assert response.status == "cancelled"
    assert queue.cancelled == [job.id]


def test_cancel_terminal_ingest_job_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="complete")
    job = repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")
    queue = FakeQueue()
    deleted_docs: list[str] = []
    monkeypatch.setattr(ingest_job_routes, "_delete_document_vectors", lambda doc_id: deleted_docs.append(doc_id) or None)

    response = _cancel(repo, job.id, user=user, queue=queue)

    assert response.status == "complete"
    assert repo.get_ingest_job(job.id).status == "complete"  # type: ignore[union-attr]
    assert queue.cancelled == []
    assert deleted_docs == []


def test_cancel_does_not_delete_vectors_when_completion_wins_status_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="processing")
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="processing",
        progress_pct=90,
        origin="upload",
    )
    queue = FakeQueue()
    deleted_docs: list[str] = []
    monkeypatch.setattr(
        ingest_job_routes,
        "_delete_document_vectors",
        lambda doc_id: deleted_docs.append(doc_id) or None,
    )

    response = _cancel(
        repo,
        job.id,
        user=user,
        queue=queue,
        job_repo=_CompleteBeforeCancelRepository(repo),
    )

    assert response.status == "complete"
    assert repo.get_ingest_job(job.id).status == "complete"  # type: ignore[union-attr]
    assert queue.cancelled == []
    assert deleted_docs == []
    assert not any(event["event_type"] == "ingest.cancelled" for event in repo.audit_events)


def test_internal_worker_status_update_does_not_resurrect_cancelled_job() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="queued")
    job = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="upload")
    repo.update_ingest_job(job.id, status="cancelled", progress_pct=20)

    asyncio.run(
        update_ingest_job_status(
            job.id,
            InternalJobStatusRequest(status="processing", progress_pct=55),
            document_repo=repo,
            job_repo=repo,
            service=ServiceTokenContext(service_name="ingestion-worker"),
        )
    )

    updated = repo.get_ingest_job(job.id)
    assert updated is not None
    assert updated.status == "cancelled"
    assert updated.progress_pct == 20


def test_visible_ingest_job_items_include_completed_at_once() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="complete")
    job = repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")

    items = _list_jobs(repo, user=user).items

    assert len(items) == 1
    assert items[0].job_id == job.id
    assert items[0].completed_at == job.completed_at


def test_visible_ingest_job_items_can_filter_to_current_uploader() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    other_user = _user("contributor", group_paths=("/ops",))
    own_document = _document(repo, user=user, status="processing")
    other_document = _document(repo, user=other_user, status="processing")
    own_job = repo.create_ingest_job(doc_id=own_document.id, status="processing", progress_pct=20, origin="upload")
    repo.create_ingest_job(doc_id=other_document.id, status="processing", progress_pct=20, origin="upload")

    items = _list_jobs(repo, user=user, origin="upload", uploaded_by_me=True).items

    assert [item.job_id for item in items] == [own_job.id]
    assert items[0].uploaded_by == user.id


class _CompleteBeforeCancelRepository:
    def __init__(self, repo: InMemoryDocumentRepository) -> None:
        self.repo = repo

    def get_ingest_job(self, job_id: str):
        return self.repo.get_ingest_job(job_id)

    def cancel_ingest_job(self, job_id: str, *, allowed_statuses: frozenset[str]):
        self.repo.update_ingest_job(
            job_id,
            status="complete",
            progress_pct=100,
            expected_statuses=frozenset({"processing"}),
        )
        return self.repo.cancel_ingest_job(job_id, allowed_statuses=allowed_statuses)


def _cancel(
    repo: InMemoryDocumentRepository,
    job_id: str,
    *,
    user: UserRecord,
    queue: FakeQueue,
    job_repo: object | None = None,
):
    return asyncio.run(
        ingest_job_routes.cancel_ingest_job(
            job_id,
            _csrf_request(),
            user=user,
            repo=repo,
            job_repo=job_repo or repo,  # type: ignore[arg-type]
            queue=queue,
        )
    )


def _list_jobs(
    repo: InMemoryDocumentRepository,
    *,
    user: UserRecord,
    origin: str | None = None,
    uploaded_by_me: bool = False,
):
    return asyncio.run(
        ingest_job_routes.list_ingest_jobs(
            job_status=None,
            origin=origin,
            group_path=None,
            search=None,
            created_from=None,
            created_to=None,
            uploaded_by_me=uploaded_by_me,
            limit=50,
            offset=0,
            user=user,
            job_repo=repo,
        )
    )


def _csrf_request() -> Request:
    token = "csrf-test-token"
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"cookie", f"{settings.csrf_cookie_name}={token}".encode("ascii")),
                (b"x-csrf-token", token.encode("ascii")),
            ],
        }
    )


def _document(repo: InMemoryDocumentRepository, *, user: UserRecord, status: str):
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
