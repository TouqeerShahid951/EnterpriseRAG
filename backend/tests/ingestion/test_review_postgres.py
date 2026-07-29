from __future__ import annotations

import os
from uuid import uuid4

import pytest

from rag.documents.adapters.postgres import PostgresDocumentRepository
from rag.ingestion.adapters.human_review_postgres import PostgresHumanReviewRepository
from rag.ingestion.adapters.image_review_postgres import PostgresImageReviewRepository
from rag.ingestion.adapters.job_postgres import PostgresIngestJobRepository


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL review integration coverage",
)
def test_postgres_human_and_image_review_lifecycles() -> None:
    assert TEST_DATABASE_URL is not None
    document_repo = PostgresDocumentRepository(TEST_DATABASE_URL)
    job_repo = PostgresIngestJobRepository(TEST_DATABASE_URL)
    human_repo = PostgresHumanReviewRepository(TEST_DATABASE_URL)
    image_repo = PostgresImageReviewRepository(TEST_DATABASE_URL)
    reviewer_id = str(uuid4())
    group_path = f"/review-{uuid4().hex[:12]}"
    source_id = f"review-test:{uuid4()}"

    with document_repo._connect() as conn:
        with conn.transaction():
            conn.execute(
                "INSERT INTO groups (path, name) VALUES (%s, %s)",
                (group_path, "Review integration test"),
            )
            conn.execute(
                """
                INSERT INTO users (
                    id, email, name, password_hash, is_active, account_type,
                    clearance_level, must_change_password
                )
                VALUES (%s, %s, %s, %s, TRUE, 'reviewer', 'NATO_RESTRICTED', FALSE)
                """,
                (
                    reviewer_id,
                    f"review-{uuid4()}@example.test",
                    "Review integration test",
                    "not-used",
                ),
            )

    document = document_repo.create_document(
        title="Review integration.pdf",
        source_id=source_id,
        group_path=group_path,
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by=reviewer_id,
        file_path="memory://review-integration.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status="human_review",
    )

    try:
        assert [
            item.id
            for item in document_repo.list_documents_by_ids((document.id,))
        ] == [document.id]
        human_job = job_repo.create_ingest_job(
            doc_id=document.id,
            status="human_review",
            progress_pct=35,
            origin="upload",
        )
        human_batch = human_repo.create_review_batch(
            job_id=human_job.id,
            doc_id=document.id,
            parsed_items=[{"index": 0, "text": "First"}, {"index": 1, "text": "Second"}],
            resume_payload={"job_id": human_job.id, "doc_id": document.id},
            review_items=[
                {"item_index": 0, "partial_text": "First"},
                {"item_index": 1, "partial_text": "Second"},
            ],
        )
        human_items = human_repo.list_review_items_for_batch(human_batch.id)
        assert human_repo.list_pending_human_review_document_ids() == (document.id,)
        first = human_repo.approve_review_item(
            human_items[0].id,
            corrected_text="First corrected",
            reviewer_id=reviewer_id,
        )
        second = human_repo.approve_review_item(
            human_items[1].id,
            corrected_text="Second corrected",
            reviewer_id=reviewer_id,
        )

        assert first is not None and first.batch_complete is False
        assert second is not None and second.batch_complete is True
        assert human_repo.get_review_batch(human_batch.id).status == "approved"  # type: ignore[union-attr]
        assert [
            item.corrected_text
            for item in human_repo.list_review_items_for_batch(human_batch.id)
        ] == ["First corrected", "Second corrected"]
        assert human_repo.list_pending_human_review_document_ids() == ()

        image_job = human_job
        image_batch = image_repo.create_image_review_batch(
            job_id=image_job.id,
            doc_id=document.id,
            parsed_items=[],
            resume_payload={"job_id": image_job.id, "doc_id": document.id},
            candidates=[
                {
                    "candidate_key": "recommended-key",
                    "filename": "recommended.png",
                    "object_path": "memory://recommended.png",
                    "content_hash": "recommended-hash",
                    "page": 1,
                    "score": 10,
                    "recommended": True,
                },
                {
                    "candidate_key": "optional-key",
                    "filename": "optional.png",
                    "object_path": "memory://optional.png",
                    "content_hash": "optional-hash",
                    "page": 2,
                    "bbox": [],
                    "score": 5,
                    "recommended": False,
                },
            ],
        )
        image_candidates = image_repo.list_image_review_candidates_for_batch(image_batch.id)
        assert image_repo.list_pending_image_review_document_ids() == (document.id,)
        recommended_candidate = next(
            candidate
            for candidate in image_candidates
            if candidate.candidate_key == "recommended-key"
        )
        assert recommended_candidate.bbox is None

        image_decision = image_repo.apply_image_review_decisions(
            image_batch.id,
            approve_candidate_ids=[],
            skip_candidate_ids=[],
            reviewer_id=reviewer_id,
            approve_recommended=True,
            skip_remaining=True,
        )

        assert image_decision is not None
        assert image_decision.batch_complete is True
        assert image_decision.batch.status == "approved"
        assert image_repo.get_image_review_approved_keys(image_batch.id) == [
            "recommended-key"
        ]
        assert image_repo.list_pending_image_review_document_ids() == ()

        cancelled_job = job_repo.create_ingest_job(
            doc_id=document.id,
            status="human_review",
            progress_pct=35,
            origin="upload",
        )
        cancelled_batch = image_repo.create_image_review_batch(
            job_id=cancelled_job.id,
            doc_id=document.id,
            parsed_items=[],
            resume_payload={"job_id": cancelled_job.id, "doc_id": document.id},
            candidates=[
                {
                    "candidate_key": "cancelled-key",
                    "filename": "cancelled.png",
                    "object_path": "memory://cancelled.png",
                    "content_hash": "cancelled-hash",
                }
            ],
        )

        cancellation = job_repo.cancel_ingest_job(
            cancelled_job.id,
            allowed_statuses=frozenset({"human_review"}),
        )

        assert cancellation.changed is True
        assert cancellation.review_items_closed == 1
        assert image_repo.get_image_review_batch(cancelled_batch.id).status == "rejected"  # type: ignore[union-attr]
        assert [
            candidate.status
            for candidate in image_repo.list_image_review_candidates_for_batch(
                cancelled_batch.id
            )
        ] == ["skipped"]
        assert image_repo.list_pending_image_review_document_ids() == ()
    finally:
        with document_repo._connect() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM documents WHERE id = %s", (document.id,))
                conn.execute("DELETE FROM users WHERE id = %s", (reviewer_id,))
                conn.execute("DELETE FROM groups WHERE path = %s", (group_path,))
