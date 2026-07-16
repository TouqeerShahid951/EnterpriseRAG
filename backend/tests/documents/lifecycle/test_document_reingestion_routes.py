from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.graphrag import document_routes as graphrag_document_routes
from rag.ingestion import document_routes as ingestion_document_routes

from documents.document_route_characterization_support import (
    FakeGraphQueue,
    FakeIngestQueue,
    FakeStorage,
    _csrf_request,
    _document,
    _graph_enrichment_service,
    _reingestion_service,
    _user,
)


def test_reingest_queues_source_payload_and_audits_success() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    queue = FakeIngestQueue()

    response = asyncio.run(
        ingestion_document_routes.reingest_document(
            document.id,
            _csrf_request("POST"),
            user=user,
            service=_reingestion_service(repo, FakeStorage(), queue),
        )
    )

    job = repo.get_ingest_job(response.job_id)
    assert job is not None and job.status == "queued" and job.origin == "reingest"
    assert queue.messages[0].doc_id == document.id
    assert queue.messages[0].file_path == document.file_path
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_reingest_queue_failure_keeps_durable_queued_job() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)

    response = asyncio.run(
        ingestion_document_routes.reingest_document(
            document.id,
            _csrf_request("POST"),
            user=user,
            service=_reingestion_service(
                repo,
                FakeStorage(),
                FakeIngestQueue(error="redis unavailable"),
            ),
        )
    )

    jobs = repo.list_ingest_jobs()
    assert len(jobs) == 1 and jobs[0].id == response.job_id
    assert jobs[0].status == "queued"
    assert jobs[0].failure_attempt_count == 0
    assert jobs[0].active_delivery_id is not None
    assert repo.audit_events[-1]["payload"]["action_result"] == "success"


def test_active_reingest_is_rejected_without_creating_another_job() -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user)
    existing = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="reingest")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            ingestion_document_routes.reingest_document(
                document.id,
                _csrf_request("POST"),
                user=user,
                service=_reingestion_service(
                    repo,
                    FakeStorage(),
                    FakeIngestQueue(),
                ),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "document_ingest_active"
    assert [job.id for job in repo.list_ingest_jobs()] == [existing.id]


def test_graph_enqueue_failure_returns_503_and_audits_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor")
    document = _document(repo, user=user, ingest_status="complete")
    job = repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            graphrag_document_routes.queue_document_graph_enrichment(
                document.id,
                _csrf_request("POST"),
                user=user,
                service=_graph_enrichment_service(
                    repo,
                    FakeGraphQueue(document_error="broker unavailable"),
                    enabled=True,
                ),
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "graphrag_enqueue_failed"
    assert repo.audit_events[-1]["event_type"] == "documents.graph_enrichment.enqueue_failed"
    assert repo.audit_events[-1]["payload"] == {"job_id": job.id, "error": "broker unavailable"}
