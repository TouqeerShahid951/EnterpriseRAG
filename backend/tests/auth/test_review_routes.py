from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from rag.api.routes import review_routes
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.repositories.document_models import DocumentRecord, ReviewItemRecord
from rag.repositories.identity_models import UserRecord
from rag.schemas.review import ImageReviewDecisionRequest, ReviewApproveRequest


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[object] = []

    def enqueue(self, message: object) -> None:
        self.enqueued.append(message)


def test_review_queue_filters_to_reviewer_document_scope() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    own_doc = _document(repo, user=_user("contributor", group_paths=("/ops",)), group_path="/ops")
    _review_item(repo, own_doc)
    other_doc = _document(repo, user=_user("contributor", group_paths=("/finance",)), group_path="/finance")
    _review_item(repo, other_doc)

    response = asyncio.run(
        review_routes.list_review_queue(
            user=reviewer,
            document_repo=repo,
            review_repo=repo,
        )
    )

    assert response.total == 1
    assert [item.doc_id for item in response.items] == [own_doc.id]


def test_contributor_can_approve_peer_document_in_same_space() -> None:
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor", group_paths=("/ops",))
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=uploader, group_path="/ops")
    item = _review_item(repo, document)
    queue = FakeQueue()

    response = asyncio.run(
        review_routes.approve_review_item(
            item.id,
            ReviewApproveRequest(corrected_text="Corrected text"),
            user=reviewer,
            document_repo=repo,
            review_repo=repo,
            job_repo=repo,
            queue=queue,  # type: ignore[arg-type]
        )
    )

    assert response.status == "approved"
    assert response.batch_complete is True
    assert len(queue.enqueued) == 1
    assert repo.list_review_items(status="pending") == []


def test_review_approval_rejects_out_of_scope_document_before_mutation() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=_user("contributor", group_paths=("/finance",)), group_path="/finance")
    item = _review_item(repo, document)
    queue = FakeQueue()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            review_routes.approve_review_item(
                item.id,
                ReviewApproveRequest(corrected_text="Corrected text"),
                user=reviewer,
                document_repo=repo,
                review_repo=repo,
                job_repo=repo,
                queue=queue,  # type: ignore[arg-type]
            )
        )

    assert exc_info.value.status_code == 403
    assert repo.list_review_items(status="pending")[0].id == item.id
    assert queue.enqueued == []


def test_image_review_queue_and_decisions_are_scoped() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    own_doc = _document(repo, user=_user("contributor", group_paths=("/ops",)), group_path="/ops")
    own_batch = _image_review_batch(repo, own_doc)
    other_doc = _document(repo, user=_user("contributor", group_paths=("/finance",)), group_path="/finance")
    other_batch = _image_review_batch(repo, other_doc)

    response = asyncio.run(
        review_routes.list_image_review_batches(
            user=reviewer,
            document_repo=repo,
            image_review_repo=repo,
        )
    )

    assert response.total == 1
    assert [batch.id for batch in response.batches] == [own_batch.id]
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            review_routes.decide_image_review_batch(
                other_batch.id,
                ImageReviewDecisionRequest(approve_recommended=True),
                user=reviewer,
                document_repo=repo,
                image_review_repo=repo,
                job_repo=repo,
                queue=FakeQueue(),  # type: ignore[arg-type]
            )
        )
    assert exc_info.value.status_code == 403
    assert repo.get_image_review_batch(other_batch.id).status == "pending"  # type: ignore[union-attr]


def _review_item(repo: InMemoryDocumentRepository, document: DocumentRecord) -> ReviewItemRecord:
    job = repo.create_ingest_job(doc_id=document.id, status="human_review", progress_pct=35, origin="upload")
    batch = repo.create_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id, "file_path": "memory://doc", "group_path": document.group_path},
        review_items=[{"item_index": 0, "partial_text": "uncertain", "confidence": 0.4}],
    )
    return repo.list_review_items_for_batch(batch.id)[0]


def _image_review_batch(repo: InMemoryDocumentRepository, document: DocumentRecord):
    job = repo.create_ingest_job(doc_id=document.id, status="human_review", progress_pct=35, origin="upload")
    return repo.create_image_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id, "file_path": "memory://doc", "group_path": document.group_path},
        candidates=[
            {
                "candidate_key": str(uuid4()),
                "filename": "page-1.png",
                "object_path": f"memory://{uuid4()}",
                "content_hash": str(uuid4()),
                "recommended": True,
            }
        ],
    )


def _document(repo: InMemoryDocumentRepository, *, user: UserRecord, group_path: str) -> DocumentRecord:
    return repo.create_document(
        title="Document.pdf",
        source_id=f"upload:{uuid4()}",
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=user.id,
        file_path="memory://document.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="human_review",
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
