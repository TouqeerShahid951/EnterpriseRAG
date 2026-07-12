from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from rag.api.routes import document_routes, ingest_job_routes
from rag.core.config import settings
from rag.graphrag import tasks as graphrag_tasks
from rag.ingestion import tasks as ingestion_tasks
from rag.repositories.document_memory import InMemoryDocumentRepository
from rag.auth.identity_models import UserRecord
from rag.ingestion.adapters.configuration_memory import InMemoryIngestConfigRepository
from rag.ingestion.configuration import IngestConfigRecord
from rag.schemas.ingest_jobs import GraphRAGCancelRequest
from rag.services.graphrag_queue import GraphRAGDocumentIndexMessage, InMemoryGraphRAGMaintenanceQueue
from rag.ingestion.worker_control import WorkerActiveTask, WorkerCapacity, WorkerControlResult


def test_successful_ingestion_does_not_automatically_queue_graph_enrichment(monkeypatch: pytest.MonkeyPatch) -> None:
    graph_dispatches: list[object] = []
    monkeypatch.setattr(
        ingestion_tasks,
        "run_ingest_document",
        lambda _task, payload: {"status": "complete", "doc_id": payload["doc_id"], "job_id": payload["job_id"]},
    )
    monkeypatch.setattr(
        graphrag_tasks.index_document_graphrag,
        "apply_async",
        lambda *args, **kwargs: graph_dispatches.append((args, kwargs)),
    )

    response = ingestion_tasks.ingest_document.run({"doc_id": "doc-1", "job_id": "job-1"})

    assert response["status"] == "complete"
    assert graph_dispatches == []


def test_graph_enrichment_is_queued_only_after_user_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="complete")
    job = repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")
    queue = InMemoryGraphRAGMaintenanceQueue()

    assert queue.document_messages == []

    response = asyncio.run(
        document_routes.queue_document_graph_enrichment(
            document.id,
            _csrf_request(),
            user=user,
            repo=repo,
            job_repo=repo,
            queue=queue,
            config_repo=_ingest_config_repo(graph_enrichment_enabled=True),
        )
    )

    assert response.status == "queued"
    assert response.job_id == job.id
    assert queue.document_messages == [
        GraphRAGDocumentIndexMessage(doc_id=document.id, job_id=job.id, reason="user_request")
    ]
    assert repo.audit_events[-1]["event_type"] == "documents.graph_enrichment.queued"


def test_graph_enrichment_rejects_disabled_workspace_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="complete")
    repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")
    queue = InMemoryGraphRAGMaintenanceQueue()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.queue_document_graph_enrichment(
                document.id,
                _csrf_request(),
                user=user,
                repo=repo,
                job_repo=repo,
                queue=queue,
                config_repo=_ingest_config_repo(graph_enrichment_enabled=False),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "graphrag_disabled"
    assert queue.document_messages == []


def test_graphrag_status_uses_workspace_enrichment_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_job_routes.settings, "graphrag_enabled", True)
    monkeypatch.setattr(ingest_job_routes, "_redis_queue_length", lambda _queue_name: (0, None))
    monkeypatch.setattr(ingest_job_routes, "_redis_queued_graphrag_tasks", lambda _queue_name: [])
    user = _user("member", group_paths=("/ops",))

    disabled = asyncio.run(
        ingest_job_routes.get_graphrag_status(
            user=user,
            control=_GraphControl(),  # type: ignore[arg-type]
            config_repo=_ingest_config_repo(graph_enrichment_enabled=False),
        )
    )
    enabled = asyncio.run(
        ingest_job_routes.get_graphrag_status(
            user=user,
            control=_GraphControl(),  # type: ignore[arg-type]
            config_repo=_ingest_config_repo(graph_enrichment_enabled=True),
        )
    )

    assert disabled.enabled is False
    assert enabled.enabled is True


def test_graph_enrichment_requires_completed_indexing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="processing")
    repo.create_ingest_job(doc_id=document.id, status="processing", progress_pct=50, origin="upload")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.queue_document_graph_enrichment(
                document.id,
                _csrf_request(),
                user=user,
                repo=repo,
                job_repo=repo,
                queue=InMemoryGraphRAGMaintenanceQueue(),
                config_repo=_ingest_config_repo(graph_enrichment_enabled=True),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "document_not_indexed"


def test_graph_enrichment_requires_document_write_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor", group_paths=("/ops",))
    reader = _user("member", group_paths=("/ops",))
    document = _document(repo, user=uploader, status="complete")
    repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.queue_document_graph_enrichment(
                document.id,
                _csrf_request(),
                user=reader,
                repo=repo,
                job_repo=repo,
                queue=InMemoryGraphRAGMaintenanceQueue(),
                config_repo=_ingest_config_repo(graph_enrichment_enabled=True),
            )
        )

    assert exc_info.value.status_code == 403


def test_graph_enrichment_rejects_same_space_peer_contributor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    repo = InMemoryDocumentRepository()
    uploader = _user("contributor", group_paths=("/ops",))
    peer = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=uploader, status="complete")
    repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            document_routes.queue_document_graph_enrichment(
                document.id,
                _csrf_request(),
                user=peer,
                repo=repo,
                job_repo=repo,
                queue=InMemoryGraphRAGMaintenanceQueue(),
                config_repo=_ingest_config_repo(graph_enrichment_enabled=True),
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "document_ingestion_forbidden"


def test_running_graph_enrichment_can_be_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryDocumentRepository()
    user = _user("contributor", group_paths=("/ops",))
    document = _document(repo, user=user, status="complete")
    job = repo.create_ingest_job(doc_id=document.id, status="complete", progress_pct=100, origin="upload")
    task_id = "graph-task-1"
    control = _GraphControl(
        WorkerActiveTask(
            task_id=task_id,
            task_name=ingest_job_routes.settings.graphrag_index_task_name,
            worker="graphrag-worker@node",
            job_id=job.id,
            doc_id=document.id,
        )
    )
    queue = InMemoryGraphRAGMaintenanceQueue()
    monkeypatch.setattr(ingest_job_routes, "_redis_queued_graphrag_tasks", lambda _queue_name: [])

    response = asyncio.run(
        ingest_job_routes.cancel_graph_enrichment(
            job.id,
            GraphRAGCancelRequest(task_id=task_id),
            _csrf_request(),
            user=user,
            repo=repo,
            job_repo=repo,
            control=control,  # type: ignore[arg-type]
            queue=queue,
        )
    )

    assert response.status == "cancelled"
    assert response.message == "Running graph enrichment cancelled."
    assert queue.cancelled_tasks == [(task_id, True)]
    assert repo.audit_events[-1]["event_type"] == "documents.graph_enrichment.cancelled"
    assert repo.audit_events[-1]["payload"]["was_running"] is True


class _GraphControl:
    def __init__(self, task: WorkerActiveTask | None = None) -> None:
        self.task = task

    def snapshot(self, desired_concurrency: int) -> WorkerControlResult:
        return WorkerControlResult(
            desired_concurrency=desired_concurrency,
            workers=(WorkerCapacity(name="graphrag-worker@node", pool_size=1, active_jobs=1 if self.task else 0),),
            apply_status="applied",
            active_job_ids=frozenset({self.task.job_id}) if self.task and self.task.job_id else frozenset(),
            active_tasks=(self.task,) if self.task else (),
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


def _ingest_config_repo(*, graph_enrichment_enabled: bool) -> InMemoryIngestConfigRepository:
    repo = InMemoryIngestConfigRepository()
    repo.save_active(IngestConfigRecord(graph_enrichment_enabled=graph_enrichment_enabled))
    return repo


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
