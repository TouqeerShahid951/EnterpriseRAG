from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from rag.ingestion.adapters import backend as backend_adapter
from rag.ingestion.adapters.backend import BackendInternalClient
from rag.ingestion.adapters.http import ServiceRequestError
from rag.ingestion.indexing import qdrant as qdrant_adapter
from rag.ingestion.indexing.qdrant import QdrantClient
from rag.internal.ingest_status_routes import (
    start_ingest_job_attempt,
    update_ingest_job_status,
)
from rag.ingestion import maintenance as ingest_maintenance
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.ingestion.adapters.configuration_memory import InMemoryIngestConfigRepository
from rag.schemas.internal import (
    InternalJobAttemptRequest,
    InternalJobStatusRequest,
    ServiceTokenContext,
)


ACTIVE_STATUSES = frozenset({"scheduled", "queued", "processing", "human_review"})


def test_attempt_claim_has_one_winner_and_same_token_is_idempotent() -> None:
    repo, _, job_id = _repository_with_job(status="queued")

    def claim(worker: int) -> tuple[str, bool]:
        token = f"worker-{worker}"
        result = repo.start_ingest_attempt(
            job_id,
            max_attempts=3,
            stale_after_seconds=120,
            run_token=token,
        )
        return token, result.claimed

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))

    winners = [token for token, claimed in results if claimed]
    assert len(winners) == 1
    current = repo.get_ingest_job(job_id)
    assert current is not None
    assert current.attempt_count == 1
    assert current.run_token == winners[0]

    repeated = repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=120,
        run_token=winners[0],
    )
    assert repeated.claimed is True
    assert repeated.job is not None and repeated.job.attempt_count == 1


def test_stale_takeover_fences_token_and_tokenless_callbacks() -> None:
    repo, _, job_id = _repository_with_job(status="queued")
    legacy = repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=120,
        run_token=None,
    )
    assert legacy.claimed is True
    assert legacy.job is not None and legacy.job.run_token is None
    assert repo.heartbeat_ingest_job(job_id, run_token=None).changed is True

    current = repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=0,
        run_token="worker-current",
    )
    assert current.claimed is True
    assert current.job is not None and current.job.run_token == "worker-current"

    stale_status = repo.update_ingest_job(
        job_id,
        status="complete",
        progress_pct=100,
        expected_statuses=frozenset({"processing"}),
        run_token=None,
    )
    stale_heartbeat = repo.heartbeat_ingest_job(job_id, run_token=None)
    stale_provenance = repo.record_ingest_parser_provenance(
        job_id,
        provenance={"parser": "stale"},
        run_token=None,
    )

    assert stale_status.changed is False
    assert stale_heartbeat.changed is False
    assert stale_provenance is None
    latest = repo.get_ingest_job(job_id)
    assert latest is not None
    assert latest.status == "processing"
    assert latest.run_token == "worker-current"


def test_status_route_rejects_stale_token_after_takeover() -> None:
    repo, _, job_id = _repository_with_job(status="queued")
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=120,
        run_token="worker-stale",
    )
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=0,
        run_token="worker-current",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            update_ingest_job_status(
                job_id,
                InternalJobStatusRequest(
                    run_token="worker-stale",
                    status="complete",
                    progress_pct=100,
                ),
                document_repo=repo,
                job_repo=repo,
                service=ServiceTokenContext(service_name="ingestion-worker"),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ingest_job_lease_lost"
    current = repo.get_ingest_job(job_id)
    assert current is not None
    assert current.status == "processing"
    assert current.run_token == "worker-current"


def test_status_route_rechecks_token_when_takeover_wins_update_race() -> None:
    repo, _, job_id = _repository_with_job(status="queued")
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=120,
        run_token="worker-stale",
    )
    racing_repo = _TakeoverBeforeUpdateRepository(repo)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            update_ingest_job_status(
                job_id,
                InternalJobStatusRequest(
                    run_token="worker-stale",
                    status="processing",
                    progress_pct=50,
                ),
                document_repo=racing_repo,  # type: ignore[arg-type]
                job_repo=racing_repo,  # type: ignore[arg-type]
                service=ServiceTokenContext(service_name="ingestion-worker"),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ingest_job_lease_lost"
    current = repo.get_ingest_job(job_id)
    assert current is not None and current.run_token == "worker-current"


def test_same_lease_progress_cannot_move_backwards() -> None:
    repo, _, job_id = _repository_with_job(status="queued")
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        run_token="worker-1",
    )
    repo.update_ingest_job(
        job_id,
        status="processing",
        progress_pct=80,
        stage_progress={"label": "newer"},
        run_token="worker-1",
    )

    repo.update_ingest_job(
        job_id,
        status="processing",
        progress_pct=40,
        stage_progress={"label": "older"},
        run_token="worker-1",
    )

    current = repo.get_ingest_job(job_id)
    assert current is not None
    assert current.progress_pct == 80
    assert current.stage_progress == {"label": "newer"}


def test_attempt_route_reports_live_final_attempt_as_busy() -> None:
    repo, _, job_id = _repository_with_job(status="queued")
    for worker in ("worker-1", "worker-2", "worker-3"):
        claimed = repo.start_ingest_attempt(
            job_id,
            max_attempts=3,
            stale_after_seconds=0,
            run_token=worker,
        )
        assert claimed.claimed is True

    response = asyncio.run(
        start_ingest_job_attempt(
            job_id,
            InternalJobAttemptRequest(run_token="worker-4"),
            job_repo=repo,
            service=ServiceTokenContext(service_name="ingestion-worker"),
        )
    )

    assert response.status == "busy"
    assert response.job_status == "processing"
    assert response.attempt_count == 3
    assert response.run_token is None


def test_cancellation_is_atomic_and_prevents_resurrection() -> None:
    repo, document_id, job_id = _repository_with_job(status="queued")
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        run_token="worker-1",
    )

    cancelled = repo.cancel_ingest_job(job_id, allowed_statuses=ACTIVE_STATUSES)
    resurrected = repo.update_ingest_job(
        job_id,
        status="complete",
        progress_pct=100,
        run_token="worker-1",
    )

    assert cancelled.changed is True
    assert cancelled.job is not None
    assert cancelled.job.status == "cancelled"
    assert cancelled.job.run_token is None
    assert resurrected.changed is False
    assert resurrected.job is not None and resurrected.job.status == "cancelled"
    document = repo.get_document(document_id)
    assert document is not None and document.ingest_status == "cancelled"


def test_backend_client_propagates_and_clears_run_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, dict[str, object] | None]] = []

    def request_json(
        _base_url: str,
        path: str,
        **kwargs: object,
    ) -> dict[str, object]:
        payload = kwargs.get("payload")
        requests.append((path, payload if isinstance(payload, dict) else None))
        if path.endswith("/attempt"):
            return {
                "status": "accepted",
                "attempt_count": 1,
                "max_attempts": 3,
                "job_status": "processing",
                "run_token": "worker-1",
            }
        return {"status": "accepted"}

    monkeypatch.setattr(backend_adapter, "request_json", request_json)
    client = BackendInternalClient(
        base_url="http://backend.test",
        service_token="service-token",
        timeout_seconds=5,
    )

    attempt = client.start_attempt(job_id="job-1", run_token="worker-1")
    client.heartbeat(job_id="job-1")
    client.record_parser_provenance(
        job_id="job-1",
        provenance={"parser": "docling"},
    )
    client.update_job(job_id="job-1", status="complete", progress_pct=100)
    client.heartbeat(job_id="job-1")

    assert attempt.run_token == "worker-1"
    assert requests[0][1] == {"run_token": "worker-1"}
    assert requests[1][1] == {"run_token": "worker-1"}
    assert requests[2][1] == {
        "run_token": "worker-1",
        "provenance": {"parser": "docling"},
    }
    assert requests[3][1] == {
        "status": "complete",
        "progress_pct": 100,
        "error_code": None,
        "error_message_safe": None,
        "run_token": "worker-1",
    }
    assert len(requests) == 4


def test_backend_client_drops_run_token_after_lease_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heartbeat_calls = 0

    def request_json(
        _base_url: str,
        path: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        nonlocal heartbeat_calls
        if path.endswith("/attempt"):
            return {
                "status": "accepted",
                "attempt_count": 1,
                "max_attempts": 3,
                "job_status": "processing",
                "run_token": "worker-1",
            }
        heartbeat_calls += 1
        raise ServiceRequestError(
            "backend",
            '{"detail":{"code":"ingest_job_lease_lost"}}',
            409,
        )

    monkeypatch.setattr(backend_adapter, "request_json", request_json)
    client = BackendInternalClient(
        base_url="http://backend.test",
        service_token="service-token",
        timeout_seconds=5,
    )
    client.start_attempt(job_id="job-1", run_token="worker-1")

    with pytest.raises(ServiceRequestError):
        client.heartbeat(job_id="job-1")
    with pytest.raises(ServiceRequestError) as exc_info:
        client.ensure_lease("job-1")

    assert heartbeat_calls == 1
    assert exc_info.value.status_code == 409


def test_qdrant_guard_stops_before_the_next_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[str] = []
    guard_calls = 0

    def request_json(_base_url: str, path: str, **_kwargs: object):
        requests.append(path)
        return {"status": "ok"}

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            raise ServiceRequestError(
                "backend",
                '{"detail":{"code":"ingest_job_lease_lost"}}',
                409,
            )

    monkeypatch.setattr(qdrant_adapter, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=5,
    )

    with pytest.raises(ServiceRequestError):
        client.replace_document(
            doc_id="doc-1",
            points=[
                {
                    "id": "point-1",
                    "vector": {"dense": [0.1], "sparse": {"indices": [1], "values": [1.0]}},
                    "payload": {"doc_id": "doc-1"},
                }
            ],
            guard=guard,
        )

    assert guard_calls == 2
    assert requests == ["/collections/documents/points/delete?wait=true"]


def test_maintenance_does_not_fail_job_heartbeat_after_stale_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _HeartbeatBeforeMaintenanceRepository()
    _, _, job_id = _populate_repository(repo, status="processing")
    job = repo.get_ingest_job(job_id)
    assert job is not None
    stale_job = replace(job, attempt_count=3)
    monkeypatch.setattr(
        ingest_maintenance,
        "list_stale_ingest_jobs",
        lambda **_kwargs: [SimpleNamespace(job=stale_job)],
    )

    recovered = ingest_maintenance.reconcile_ingestion_jobs(
        document_repo=repo,
        queue=object(),  # type: ignore[arg-type]
        control=_MaintenanceControl(),  # type: ignore[arg-type]
        config_repo=InMemoryIngestConfigRepository(),
    )

    assert recovered == []
    assert repo.stale_before is not None
    current = repo.get_ingest_job(job_id)
    assert current is not None and current.status == "processing"
    assert repo.audit_events == []


def test_maintenance_uses_observed_token_to_fail_stale_exhausted_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, job_id = _repository_with_job(status="queued")
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        run_token="worker-stale",
    )
    current = repo.get_ingest_job(job_id)
    assert current is not None
    old = datetime.now(UTC) - timedelta(minutes=5)
    stale_job = replace(
        current,
        attempt_count=3,
        last_heartbeat_at=old,
        updated_at=old,
    )
    repo._jobs[job_id] = stale_job
    monkeypatch.setattr(
        ingest_maintenance,
        "list_stale_ingest_jobs",
        lambda **_kwargs: [SimpleNamespace(job=stale_job)],
    )

    recovered = ingest_maintenance.reconcile_ingestion_jobs(
        document_repo=repo,
        queue=object(),  # type: ignore[arg-type]
        control=_MaintenanceControl(),  # type: ignore[arg-type]
        config_repo=InMemoryIngestConfigRepository(),
    )

    assert recovered == []
    failed = repo.get_ingest_job(job_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.run_token is None
    assert repo.audit_events[-1]["event_type"] == "internal.ingest.exhausted"


class _HeartbeatBeforeMaintenanceRepository(InMemoryDocumentRepository):
    def __init__(self) -> None:
        super().__init__()
        self.stale_before: datetime | None = None

    def update_ingest_job(self, job_id: str, **kwargs: object):
        self.stale_before = kwargs.get("stale_before")  # type: ignore[assignment]
        self.heartbeat_ingest_job(job_id, run_token=None)
        return super().update_ingest_job(job_id, **kwargs)  # type: ignore[arg-type]


class _TakeoverBeforeUpdateRepository:
    def __init__(self, repo: InMemoryDocumentRepository) -> None:
        self.repo = repo

    def get_ingest_job(self, job_id: str):
        return self.repo.get_ingest_job(job_id)

    def update_ingest_job(self, job_id: str, **kwargs: object):
        self.repo.start_ingest_attempt(
            job_id,
            max_attempts=3,
            stale_after_seconds=0,
            run_token="worker-current",
        )
        return self.repo.update_ingest_job(job_id, **kwargs)  # type: ignore[arg-type]


class _MaintenanceControl:
    def apply(self, _worker_concurrency: int):
        return SimpleNamespace(active_job_ids=frozenset())


def _repository_with_job(
    *,
    status: str,
) -> tuple[InMemoryDocumentRepository, str, str]:
    repo = InMemoryDocumentRepository()
    return _populate_repository(repo, status=status)


def _populate_repository(
    repo: InMemoryDocumentRepository,
    *,
    status: str,
) -> tuple[InMemoryDocumentRepository, str, str]:
    document = repo.create_document(
        title="Ingest.pdf",
        source_id=f"upload:{uuid4()}",
        group_path="/ops",
        clearance_level="NATO_RESTRICTED",
        doc_type=None,
        effective_date=None,
        expiry_date=None,
        description=None,
        uploaded_by="user-1",
        file_path="memory://ingest.pdf",
        content_hash=str(uuid4()),
        pending_supersedes=[],
        ingest_status=status,
    )
    job = repo.create_ingest_job(
        doc_id=document.id,
        status=status,
        progress_pct=0,
        origin="upload",
    )
    return repo, document.id, job.id
