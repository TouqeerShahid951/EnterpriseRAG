from uuid import uuid4

import pytest

from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.ingestion.review_models import ImageReviewBatchClosedError


def test_image_review_decision_returns_none_for_unknown_batch() -> None:
    repo = InMemoryDocumentRepository()

    decision = repo.apply_image_review_decisions(
        str(uuid4()),
        approve_candidate_ids=[],
        skip_candidate_ids=[],
        reviewer_id="reviewer",
    )

    assert decision is None


def test_image_review_decisions_are_partial_and_idempotent() -> None:
    repo, batch_id, candidate_ids = _repository_with_batch()

    partial = repo.apply_image_review_decisions(
        batch_id,
        approve_candidate_ids=[candidate_ids[0]],
        skip_candidate_ids=[],
        reviewer_id="reviewer",
    )
    repeated = repo.apply_image_review_decisions(
        batch_id,
        approve_candidate_ids=[candidate_ids[0]],
        skip_candidate_ids=[],
        reviewer_id="reviewer",
    )

    assert partial is not None
    assert partial.batch.status == "pending"
    assert partial.batch_complete is False
    assert [candidate.id for candidate in partial.candidates] == [candidate_ids[0]]
    assert repeated is not None
    assert repeated.batch.status == "pending"
    assert repeated.batch_complete is False
    assert repeated.candidates == ()


def test_image_review_combined_decision_completes_batch() -> None:
    repo, batch_id, candidate_ids = _repository_with_batch()

    decision = repo.apply_image_review_decisions(
        batch_id,
        approve_candidate_ids=[],
        skip_candidate_ids=[],
        reviewer_id="reviewer",
        approve_recommended=True,
        skip_remaining=True,
    )

    assert decision is not None
    assert decision.batch.status == "approved"
    assert decision.batch_complete is True
    assert {candidate.id for candidate in decision.candidates} == set(candidate_ids)
    candidates = repo.list_image_review_candidates_for_batch(batch_id)
    assert [candidate.status for candidate in candidates] == ["approved", "skipped"]
    assert [candidate.candidate_key for candidate in candidates if candidate.status == "approved"] == ["recommended"]


def test_image_review_decision_rejects_cancelled_batch() -> None:
    repo, batch_id, _ = _repository_with_batch()
    batch = repo.get_image_review_batch(batch_id)
    assert batch is not None
    repo.cancel_ingest_job(batch.job_id, allowed_statuses=frozenset({"human_review"}))

    with pytest.raises(ImageReviewBatchClosedError):
        repo.apply_image_review_decisions(
            batch_id,
            approve_candidate_ids=[],
            skip_candidate_ids=[],
            reviewer_id="reviewer",
            approve_recommended=True,
        )

    assert repo.get_image_review_batch(batch_id).status == "rejected"  # type: ignore[union-attr]


def _repository_with_batch() -> tuple[InMemoryDocumentRepository, str, list[str]]:
    repo = InMemoryDocumentRepository()
    document = repo.create_document(
        title="Review.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by="reviewer",
        file_path="memory://review.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="human_review",
    )
    job = repo.create_ingest_job(
        doc_id=document.id,
        status="human_review",
        progress_pct=35,
        origin="upload",
    )
    candidate_ids = [str(uuid4()), str(uuid4())]
    batch = repo.create_image_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id},
        candidates=[
            {
                "id": candidate_ids[0],
                "candidate_key": "recommended",
                "filename": "page-1.png",
                "object_path": "memory://page-1.png",
                "content_hash": "hash-1",
                "page": 1,
                "score": 10,
                "recommended": True,
            },
            {
                "id": candidate_ids[1],
                "candidate_key": "optional",
                "filename": "page-2.png",
                "object_path": "memory://page-2.png",
                "content_hash": "hash-2",
                "page": 2,
                "score": 5,
                "recommended": False,
            },
        ],
    )
    return repo, batch.id, candidate_ids
