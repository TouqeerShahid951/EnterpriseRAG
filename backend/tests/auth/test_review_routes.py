from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from rag.ingestion.review import routes as review_routes
from rag.ingestion.review.dependencies import get_human_review_repository, get_image_review_repository
from rag.ingestion.review.models import ReviewItemRecord
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.models import DocumentRecord
from rag.documents.adapters.postgres import PostgresDocumentRepository
from rag.documents.repository import get_document_repository
from rag.ingestion.adapters.human_review_postgres import PostgresHumanReviewRepository
from rag.auth.identity_models import UserRecord
from rag.ingestion.adapters.image_review_postgres import PostgresImageReviewRepository
from rag.ingestion.adapters.job_postgres import PostgresIngestJobRepository
from rag.ingestion.job_dependencies import get_ingest_job_repository
from rag.ingestion.review.schemas import ImageReviewDecisionRequest, ReviewApproveRequest
from rag.ingestion.delivery import IngestDeliveryService, dispatch_pending_deliveries


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[object] = []

    def enqueue(self, message: object) -> None:
        self.enqueued.append(message)


class FailOnceQueue(FakeQueue):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def enqueue(self, message: object) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("queue unavailable")
        super().enqueue(message)


def test_review_ports_are_independently_substitutable() -> None:
    assert get_human_review_repository is not get_document_repository
    assert get_image_review_repository is not get_document_repository
    assert get_ingest_job_repository is not get_document_repository
    assert not issubclass(PostgresDocumentRepository, PostgresHumanReviewRepository)
    assert not issubclass(PostgresDocumentRepository, PostgresImageReviewRepository)
    assert not issubclass(PostgresDocumentRepository, PostgresIngestJobRepository)


@pytest.mark.parametrize(
    "provider",
    [get_human_review_repository, get_image_review_repository, get_ingest_job_repository],
)
def test_document_override_flows_to_capability_provider(provider) -> None:
    repo = InMemoryDocumentRepository()
    app = FastAPI()

    @app.get("/probe")
    def probe(capability_repo: object = Depends(provider)) -> dict[str, bool]:
        return {"same_repository": capability_repo is repo}

    app.dependency_overrides[get_document_repository] = lambda: repo

    assert TestClient(app).get("/probe").json() == {"same_repository": True}


def test_review_queue_filters_to_reviewer_document_scope() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    own_doc = _document(repo, user=_user("contributor", group_paths=("/ops",)), group_path="/ops")
    _review_item(repo, own_doc)
    other_doc = _document(repo, user=_user("contributor", group_paths=("/finance",)), group_path="/finance")
    _review_item(repo, other_doc)

    response = asyncio.run(review_routes.list_review_queue(user=reviewer, document_repo=repo, review_repo=repo))

    assert response.total == 1
    assert [item.doc_id for item in response.items] == [own_doc.id]


def test_contributor_can_approve_peer_document_in_same_space() -> None:
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor", group_paths=("/ops",))
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=uploader, group_path="/ops")
    item = _review_item(repo, document)
    queue = FakeQueue()

    response = _approve(repo, item.id, reviewer=reviewer, queue=queue)

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
        _approve(repo, item.id, reviewer=reviewer, queue=queue)

    assert exc_info.value.status_code == 403
    assert repo.list_review_items(status="pending")[0].id == item.id
    assert queue.enqueued == []


def test_completed_text_review_is_delivered_after_queue_recovers() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=reviewer, group_path="/ops")
    item = _review_item(repo, document)
    queue = FailOnceQueue()

    response = _approve(repo, item.id, reviewer=reviewer, queue=queue)

    batch = repo.get_review_batch(item.batch_id)
    assert batch is not None
    job = repo.get_ingest_job(batch.job_id)
    assert response.batch_complete is True
    assert job is not None and job.status == "queued"
    assert job.review_resume_count == 1
    assert job.failure_attempt_count == 0
    assert queue.attempts == 1

    delivered = dispatch_pending_deliveries(
        IngestDeliveryService(repo),
        queue,  # type: ignore[arg-type]
        now=datetime.now(UTC) + timedelta(seconds=6),
    )
    repeated = _approve(repo, item.id, reviewer=reviewer, queue=queue)

    assert delivered.published_count == 1
    assert repeated.batch_complete is True
    assert queue.attempts == 2
    assert len(queue.enqueued) == 1
    assert repo.get_ingest_job(batch.job_id).review_resume_count == 1  # type: ignore[union-attr]


def test_image_review_queue_and_decisions_are_scoped() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    own_doc = _document(repo, user=_user("contributor", group_paths=("/ops",)), group_path="/ops")
    own_batch = _image_review_batch(repo, own_doc)
    other_doc = _document(repo, user=_user("contributor", group_paths=("/finance",)), group_path="/finance")
    other_batch = _image_review_batch(repo, other_doc)

    response = asyncio.run(review_routes.list_image_review_batches(user=reviewer, document_repo=repo, image_review_repo=repo))

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


def test_image_review_decision_rejects_cancelled_batch() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=reviewer, group_path="/ops")
    batch = _image_review_batch(repo, document)
    repo.cancel_ingest_job(batch.job_id, allowed_statuses=frozenset({"human_review"}))
    queue = FakeQueue()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            review_routes.decide_image_review_batch(
                batch.id,
                ImageReviewDecisionRequest(approve_recommended=True),
                user=reviewer,
                document_repo=repo,
                image_review_repo=repo,
                job_repo=repo,
                queue=queue,  # type: ignore[arg-type]
            )
        )

    assert exc_info.value.status_code == 409
    assert queue.enqueued == []
    assert repo.get_image_review_batch(batch.id).status == "rejected"  # type: ignore[union-attr]


def test_completed_image_review_reports_missing_ingest_job() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=reviewer, group_path="/ops")
    batch = _image_review_batch(repo, document)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            review_routes.decide_image_review_batch(
                batch.id,
                ImageReviewDecisionRequest(approve_recommended=True),
                user=reviewer,
                document_repo=repo,
                image_review_repo=repo,
                job_repo=_MissingJobRepository(),  # type: ignore[arg-type]
                queue=FakeQueue(),  # type: ignore[arg-type]
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ingest_job_not_found"


def test_completed_image_review_decision_is_idempotent() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=reviewer, group_path="/ops")
    batch = _image_review_batch(repo, document)
    queue = FakeQueue()

    first = asyncio.run(
        review_routes.decide_image_review_batch(
            batch.id,
            ImageReviewDecisionRequest(approve_recommended=True),
            user=reviewer,
            document_repo=repo,
            image_review_repo=repo,
            job_repo=repo,
            queue=queue,  # type: ignore[arg-type]
        )
    )
    audit_count = len(repo.list_audit_events(limit=100))
    repeated = asyncio.run(
        review_routes.decide_image_review_batch(
            batch.id,
            ImageReviewDecisionRequest(approve_recommended=True),
            user=reviewer,
            document_repo=repo,
            image_review_repo=repo,
            job_repo=repo,
            queue=queue,  # type: ignore[arg-type]
        )
    )

    assert first.batch_complete is True
    assert repeated.batch_complete is True
    assert len(queue.enqueued) == 1
    assert len(repo.list_audit_events(limit=100)) == audit_count


def test_completed_image_review_is_delivered_after_queue_recovers() -> None:
    repo = InMemoryDocumentRepository()
    reviewer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=reviewer, group_path="/ops")
    batch = _image_review_batch(repo, document)
    queue = FailOnceQueue()
    payload = ImageReviewDecisionRequest(approve_recommended=True)

    response = asyncio.run(
        review_routes.decide_image_review_batch(
            batch.id,
            payload,
            user=reviewer,
            document_repo=repo,
            image_review_repo=repo,
            job_repo=repo,
            queue=queue,  # type: ignore[arg-type]
        )
    )

    job = repo.get_ingest_job(batch.job_id)
    assert response.batch_complete is True
    assert job is not None and job.status == "queued"
    assert job.review_resume_count == 1
    assert job.failure_attempt_count == 0
    assert queue.attempts == 1

    delivered = dispatch_pending_deliveries(
        IngestDeliveryService(repo),
        queue,  # type: ignore[arg-type]
        now=datetime.now(UTC) + timedelta(seconds=6),
    )

    repeated = asyncio.run(
        review_routes.decide_image_review_batch(
            batch.id,
            payload,
            user=reviewer,
            document_repo=repo,
            image_review_repo=repo,
            job_repo=repo,
            queue=queue,  # type: ignore[arg-type]
        )
    )

    assert delivered.published_count == 1
    assert repeated.batch_complete is True
    assert queue.attempts == 2
    assert len(queue.enqueued) == 1
    assert repo.get_ingest_job(batch.job_id).review_resume_count == 1  # type: ignore[union-attr]


def _approve(
    repo: InMemoryDocumentRepository,
    item_id: str,
    *,
    reviewer: UserRecord,
    queue: FakeQueue,
):
    return asyncio.run(
        review_routes.approve_review_item(
            item_id,
            ReviewApproveRequest(corrected_text="Corrected text"),
            user=reviewer,
            document_repo=repo,
            review_repo=repo,
            job_repo=repo,
            queue=queue,  # type: ignore[arg-type]
        )
    )


class _MissingJobRepository:
    def get_ingest_job(self, _job_id: str):
        return None


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
