from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from rag.internal.review_batch_routes import get_image_review_approved_keys
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.adapters.postgres import PostgresDocumentRepository
from rag.ingestion.adapters.human_review_postgres import (
    PostgresHumanReviewRepository,
    review_batch_from_row,
)
from rag.ingestion.adapters.image_review_postgres import (
    PostgresImageReviewRepository,
    image_review_batch_from_row,
)
from rag.ingestion.review.dependencies import (
    human_review_repository_for,
    image_review_repository_for,
)


def test_memory_review_providers_reuse_document_repository_instance() -> None:
    document_repo = InMemoryDocumentRepository()

    assert human_review_repository_for(document_repo) is document_repo
    assert image_review_repository_for(document_repo) is document_repo


def test_postgres_review_providers_use_dedicated_adapters() -> None:
    document_repo = PostgresDocumentRepository("postgresql://repository.test/db")

    human_repo = human_review_repository_for(document_repo)
    image_repo = image_review_repository_for(document_repo)

    assert isinstance(human_repo, PostgresHumanReviewRepository)
    assert isinstance(image_repo, PostgresImageReviewRepository)
    assert human_repo.database_url == document_repo.database_url
    assert image_repo.database_url == document_repo.database_url


def test_review_providers_reject_unsupported_document_adapter() -> None:
    unsupported = object()

    with pytest.raises(RuntimeError, match="human-review repository"):
        human_review_repository_for(unsupported)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="image-review repository"):
        image_review_repository_for(unsupported)  # type: ignore[arg-type]


def test_postgres_review_row_mappers_are_feature_owned() -> None:
    assert review_batch_from_row.__module__ == "rag.ingestion.adapters.human_review_postgres"
    assert image_review_batch_from_row.__module__ == "rag.ingestion.adapters.image_review_postgres"


def test_approved_keys_internal_contract_is_preserved() -> None:
    repo, batch_id, approved_candidate_id = _image_review_repository()

    with pytest.raises(HTTPException) as pending_error:
        asyncio.run(
            get_image_review_approved_keys(
                batch_id,
                image_review_repo=repo,
            )
        )
    assert pending_error.value.status_code == 409
    assert pending_error.value.detail["code"] == "image_review_batch_not_approved"

    repo.apply_image_review_decisions(
        batch_id,
        approve_candidate_ids=[approved_candidate_id],
        skip_candidate_ids=[],
        skip_remaining=True,
        reviewer_id="reviewer-1",
    )
    response = asyncio.run(
        get_image_review_approved_keys(
            batch_id,
            image_review_repo=repo,
        )
    )
    assert response.candidate_keys == ["approved-key"]

    with pytest.raises(HTTPException) as missing_error:
        asyncio.run(
            get_image_review_approved_keys(
                str(uuid4()),
                image_review_repo=repo,
            )
        )
    assert missing_error.value.status_code == 404
    assert missing_error.value.detail["code"] == "image_review_batch_not_found"


def _image_review_repository() -> tuple[InMemoryDocumentRepository, str, str]:
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
        uploaded_by="reviewer-1",
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
    approved_candidate_id = str(uuid4())
    batch = repo.create_image_review_batch(
        job_id=job.id,
        doc_id=document.id,
        parsed_items=[],
        resume_payload={"job_id": job.id, "doc_id": document.id},
        candidates=[
            {
                "id": approved_candidate_id,
                "candidate_key": "approved-key",
                "filename": "approved.png",
                "object_path": "memory://approved.png",
                "content_hash": "approved-hash",
                "page": 1,
                "score": 10,
                "recommended": True,
            },
            {
                "id": str(uuid4()),
                "candidate_key": "skipped-key",
                "filename": "skipped.png",
                "object_path": "memory://skipped.png",
                "content_hash": "skipped-hash",
                "page": 2,
                "score": 5,
                "recommended": False,
            },
        ],
    )
    return repo, batch.id, approved_candidate_id
