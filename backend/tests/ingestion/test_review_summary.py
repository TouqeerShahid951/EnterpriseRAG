from __future__ import annotations

import asyncio
from uuid import uuid4

from rag.auth.identity_models import UserRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.models import DocumentRecord
from rag.ingestion.review.summary import count_visible_pending_review_documents
from rag.ingestion.review.summary_routes import summarize_review_queue


def test_review_summary_deduplicates_documents_and_applies_review_scope() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user(group_paths=("/ops",))
    visible = _document(repo, reviewer, group_path="/ops")
    _human_batch(repo, visible, item_count=2)
    _image_batch(repo, visible, candidate_count=2)
    hidden = _document(repo, reviewer, group_path="/finance")
    _human_batch(repo, hidden)
    shared = _document(repo, reviewer, group_path="/ops")
    repo.replace_document_shares(shared.id, group_paths=["/finance"], actor_id=reviewer.id)
    _human_batch(repo, shared)

    response = asyncio.run(
        summarize_review_queue(
            user=reviewer,
            document_repo=repo,
            human_review_repo=repo,
            image_review_repo=repo,
        )
    )

    assert response.pending_document_count == 1


def test_review_summary_clears_only_when_the_document_is_no_longer_pending() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user(group_paths=("/ops",))
    document = _document(repo, reviewer, group_path="/ops")
    human_batch = _human_batch(repo, document, item_count=2)
    human_items = repo.list_review_items_for_batch(human_batch.id)

    assert _count(repo, reviewer) == 1
    repo.approve_review_item(human_items[0].id, corrected_text="First", reviewer_id=reviewer.id)
    assert _count(repo, reviewer) == 1
    repo.approve_review_item(human_items[1].id, corrected_text="Second", reviewer_id=reviewer.id)
    assert _count(repo, reviewer) == 0

    image_batch = _image_batch(repo, document, candidate_count=2)
    candidates = repo.list_image_review_candidates_for_batch(image_batch.id)
    repo.apply_image_review_decisions(
        image_batch.id,
        approve_candidate_ids=[candidates[0].id],
        skip_candidate_ids=[],
        reviewer_id=reviewer.id,
    )
    assert _count(repo, reviewer) == 1
    repo.apply_image_review_decisions(
        image_batch.id,
        approve_candidate_ids=[],
        skip_candidate_ids=[],
        skip_remaining=True,
        reviewer_id=reviewer.id,
    )
    assert _count(repo, reviewer) == 0


def test_review_summary_clears_when_a_review_job_is_cancelled() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user(group_paths=("/ops",))
    document = _document(repo, reviewer, group_path="/ops")
    human_batch = _human_batch(repo, document)

    assert _count(repo, reviewer) == 1
    repo.cancel_ingest_job(
        human_batch.job_id,
        allowed_statuses=frozenset({"human_review"}),
    )
    assert _count(repo, reviewer) == 0

    image_batch = _image_batch(repo, document)
    assert _count(repo, reviewer) == 1
    repo.cancel_ingest_job(
        image_batch.job_id,
        allowed_statuses=frozenset({"human_review"}),
    )
    assert _count(repo, reviewer) == 0


def _count(repo: InMemoryDocumentRepository, reviewer: UserRecord) -> int:
    return count_visible_pending_review_documents(
        user=reviewer,
        document_repo=repo,
        human_review_repo=repo,
        image_review_repo=repo,
    )


def _human_batch(
    repo: InMemoryDocumentRepository,
    document: DocumentRecord,
    *,
    item_count: int = 1,
):
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="human_review",
        progress_pct=35,
        origin="upload",
    )
    return repo.create_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id},
        review_items=[
            {"item_index": index, "partial_text": f"Block {index}"}
            for index in range(item_count)
        ],
    )


def _image_batch(
    repo: InMemoryDocumentRepository,
    document: DocumentRecord,
    *,
    candidate_count: int = 1,
):
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="human_review",
        progress_pct=35,
        origin="upload",
    )
    return repo.create_image_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id},
        candidates=[
            {
                "candidate_key": f"candidate-{index}",
                "filename": f"candidate-{index}.png",
                "object_path": f"memory://candidate-{index}.png",
                "content_hash": f"hash-{index}",
            }
            for index in range(candidate_count)
        ],
    )


def _document(
    repo: InMemoryDocumentRepository,
    uploader: UserRecord,
    *,
    group_path: str,
) -> DocumentRecord:
    return repo.create_document(
        title="Review.pdf",
        source_id=f"upload:{uuid4()}",
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=uploader.id,
        file_path="memory://review.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="human_review",
    )


def _user(*, group_paths: tuple[str, ...]) -> UserRecord:
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
        group_paths=group_paths,
    )
