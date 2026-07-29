from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from rag.internal.ingest_status_routes import start_ingest_job_attempt, update_ingest_job_status
from rag.ingestion import maintenance as ingest_maintenance
from rag.documents.adapters.memory import InMemoryDocumentRepository
from rag.documents.adapters.postgres import PostgresDocumentRepository
from rag.ingestion.adapters.configuration_memory import InMemoryIngestConfigRepository
from rag.ingestion.job_models import (
    IngestJobAccess,
    IngestJobFilters,
    IngestJobMutationResult,
)
from rag.ingestion.adapters.job_postgres import PostgresIngestJobRepository
from rag.ingestion.job_dependencies import get_ingest_job_repository, ingest_job_repository_for
from rag.ingestion.internal_schemas import (
    InternalJobAttemptRequest,
    InternalJobStatusRequest,
)


ACTIVE_STATUSES = frozenset({"scheduled", "queued", "processing", "human_review"})


def test_provider_keeps_document_and_ingest_job_postgres_adapters_independent() -> None:
    document_repo = PostgresDocumentRepository("postgresql://repository.test/db")

    job_repo = ingest_job_repository_for(document_repo)

    assert isinstance(job_repo, PostgresIngestJobRepository)
    assert job_repo.database_url == document_repo.database_url
    assert all(
        not hasattr(document_repo, method)
        for method in (
            "create_ingest_job",
            "get_ingest_job",
            "list_ingest_jobs",
            "update_ingest_job",
            "start_ingest_attempt",
            "heartbeat_ingest_job",
            "cancel_ingest_job",
        )
    )


def test_provider_reuses_combined_memory_adapter_for_dependency_overrides() -> None:
    repository = InMemoryDocumentRepository()

    assert ingest_job_repository_for(repository) is repository
    assert get_ingest_job_repository(repository) is repository


def test_postgres_search_uses_one_scoped_statement_for_page_and_total() -> None:
    repository = _CapturingPostgresIngestJobRepository()

    page = repository.search_visible_ingest_jobs(
        access=IngestJobAccess(
            clearance_levels=("NATO_RESTRICTED", "NATO_CONFIDENTIAL"),
            group_paths=("/ops",),
        ),
        filters=IngestJobFilters(
            status="processing",
            search="report",
            uploaded_by_user_id="user-1",
        ),
        limit=1,
        offset=1,
    )

    assert len(repository.queries) == 1
    query, params = repository.queries[0]
    assert "WITH filtered AS" in query
    assert "document_shares" in query
    assert "COUNT(*)::bigint AS total" in query
    assert params[-2:] == (1, 1)
    assert page.total == 2
    assert [item.document_title for item in page.items] == ["Report.pdf"]


def test_postgres_summary_uses_one_scoped_aggregate_statement() -> None:
    repository = _CapturingPostgresIngestSummaryRepository()

    summary = repository.summarize_visible_ingest_jobs(
        access=IngestJobAccess(
            clearance_levels=("NATO_RESTRICTED",),
            group_paths=("/ops",),
        ),
        filters=IngestJobFilters(),
    )

    assert len(repository.queries) == 1
    query, params = repository.queries[0]
    assert "ROW_NUMBER() OVER" in query
    assert "GROUP BY stage" in query
    assert "GROUP BY origin" in query
    assert "LIMIT" not in query
    assert params == (
        ["NATO_RESTRICTED"],
        ["/ops"],
        ["/ops"],
    )
    assert summary.total == 4
    assert summary.active == 1
    assert summary.needs_attention == 2
    assert summary.status_counts == {"complete": 3, "failed": 1}
    assert summary.stage_counts == {"complete": 3, "failed": 1}
    assert summary.origin_counts == {"upload": 4}


def test_update_compare_and_set_rejects_stale_status_and_cancelled_resurrection() -> None:
    repo, document_id, job_id = _repository_with_job(status="queued")

    claimed = repo.update_ingest_job(
        job_id,
        status="processing",
        progress_pct=10,
        expected_statuses=frozenset({"queued"}),
    )
    stale = repo.update_ingest_job(
        job_id,
        status="failed",
        progress_pct=100,
        expected_statuses=frozenset({"queued"}),
    )
    cancelled = repo.cancel_ingest_job(job_id, allowed_statuses=ACTIVE_STATUSES)
    resurrected = repo.update_ingest_job(job_id, status="complete", progress_pct=100)

    assert claimed.changed is True
    assert stale.changed is False
    assert stale.job is not None and stale.job.status == "processing"
    assert cancelled.changed is True
    assert resurrected.changed is False
    assert resurrected.job is not None and resurrected.job.status == "cancelled"
    assert repo.get_document(document_id).ingest_status == "cancelled"  # type: ignore[union-attr]


def test_attempt_claim_reports_one_winner_then_busy_stale_and_exhausted() -> None:
    repo, _, job_id = _repository_with_job(status="queued")

    first = repo.start_ingest_attempt(
        job_id,
        max_attempts=2,
        stale_after_seconds=120,
        run_token="worker-1",
    )
    busy = repo.start_ingest_attempt(
        job_id,
        max_attempts=2,
        stale_after_seconds=120,
        run_token="worker-2",
    )
    stale_reclaim = repo.start_ingest_attempt(
        job_id,
        max_attempts=2,
        stale_after_seconds=0,
        run_token="worker-2",
    )
    exhausted = repo.start_ingest_attempt(
        job_id,
        max_attempts=2,
        stale_after_seconds=0,
        run_token="worker-3",
    )

    assert first.claimed is True
    assert first.job is not None and first.job.attempt_count == 1
    assert first.job.run_token == "worker-1"
    assert busy.claimed is False
    assert busy.job is not None and busy.job.attempt_count == 1
    assert stale_reclaim.claimed is True
    assert stale_reclaim.job is not None and stale_reclaim.job.attempt_count == 2
    assert stale_reclaim.job.run_token == "worker-2"
    assert exhausted.claimed is False
    assert exhausted.job is not None and exhausted.job.attempt_count == 2


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
        )
    )

    assert response.status == "busy"
    assert response.job_status == "processing"
    assert response.attempt_count == 3
    assert response.run_token is None


def test_ingest_attempt_run_token_fences_stale_worker_mutations() -> None:
    repo, _, job_id = _repository_with_job(status="queued")

    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=120,
        run_token="worker-1",
    )
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=0,
        run_token="worker-2",
    )

    old_heartbeat = repo.heartbeat_ingest_job(job_id, run_token="worker-1")
    old_update = repo.update_ingest_job(
        job_id,
        status="complete",
        progress_pct=100,
        run_token="worker-1",
    )
    old_provenance = repo.record_ingest_parser_provenance(
        job_id,
        provenance={"parser": "stale"},
        run_token="worker-1",
    )
    current_provenance = repo.record_ingest_parser_provenance(
        job_id,
        provenance={"parser": "current"},
        run_token="worker-2",
    )
    completed = repo.update_ingest_job(
        job_id,
        status="complete",
        progress_pct=100,
        run_token="worker-2",
    )

    assert old_heartbeat.changed is False
    assert old_update.changed is False
    assert old_update.job is not None and old_update.job.run_token == "worker-2"
    assert old_provenance is None
    assert current_provenance is not None
    assert current_provenance.parser_provenance == {"parser": "current"}
    assert completed.changed is True
    assert completed.job is not None
    assert completed.job.status == "complete"
    assert completed.job.run_token is None


def test_heartbeat_only_changes_processing_jobs() -> None:
    repo, _, job_id = _repository_with_job(status="queued")

    queued = repo.heartbeat_ingest_job(job_id)
    repo.start_ingest_attempt(job_id, max_attempts=3)
    processing = repo.heartbeat_ingest_job(job_id)
    repo.cancel_ingest_job(job_id, allowed_statuses=ACTIVE_STATUSES)
    cancelled = repo.heartbeat_ingest_job(job_id)

    assert queued.changed is False
    assert processing.changed is True
    assert processing.job is not None and processing.job.last_heartbeat_at is not None
    assert cancelled.changed is False
    assert cancelled.job is not None and cancelled.job.status == "cancelled"


def test_parser_provenance_persists_with_audit_event() -> None:
    repo, _, job_id = _repository_with_job(status="processing")

    job = repo.record_ingest_parser_provenance(
        job_id,
        provenance={"parser": "docling", "version": "2"},
    )

    assert job is not None
    assert job.parser_provenance == {"parser": "docling", "version": "2"}
    assert repo.audit_events[-1]["event_type"] == "internal.ingest.parser_provenance"


def test_worker_terminal_callback_that_loses_cancel_race_does_not_audit_requested_status() -> None:
    repo, _, job_id = _repository_with_job(status="processing")
    racing_repo = _CancelBeforeUpdateRepository(repo)

    asyncio.run(
        update_ingest_job_status(
            job_id,
            InternalJobStatusRequest(status="complete", progress_pct=100),
            document_repo=repo,
            job_repo=racing_repo,  # type: ignore[arg-type]
        )
    )

    assert repo.get_ingest_job(job_id).status == "cancelled"  # type: ignore[union-attr]
    assert not any(event["event_type"] == "internal.ingest.status" for event in repo.audit_events)


def test_worker_status_callback_rejects_lost_run_token() -> None:
    repo, _, job_id = _repository_with_job(status="queued")
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=120,
        run_token="worker-1",
    )
    repo.start_ingest_attempt(
        job_id,
        max_attempts=3,
        stale_after_seconds=0,
        run_token="worker-2",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            update_ingest_job_status(
                job_id,
                InternalJobStatusRequest(
                    run_token="worker-1",
                    status="complete",
                    progress_pct=100,
                ),
                document_repo=repo,
                job_repo=repo,
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "ingest_job_lease_lost"
    current = repo.get_ingest_job(job_id)
    assert current is not None
    assert current.status == "processing"
    assert current.run_token == "worker-2"


def test_maintenance_does_not_fail_or_audit_job_heartbeat_after_stale_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, job_id = _repository_with_job(status="processing")
    job = repo.get_ingest_job(job_id)
    assert job is not None
    stale_job = replace(job, attempt_count=3, failure_attempt_count=3)
    racing_repo = _HeartbeatBeforeMaintenanceRepository(repo)
    monkeypatch.setattr(
        ingest_maintenance,
        "list_stale_ingest_jobs",
        lambda **_kwargs: [SimpleNamespace(job=stale_job)],
    )

    recovered = ingest_maintenance.reconcile_ingestion_jobs(
        document_repo=repo,
        job_repo=racing_repo,  # type: ignore[arg-type]
        queue=object(),  # type: ignore[arg-type]
        control=_MaintenanceControl(),  # type: ignore[arg-type]
        config_repo=InMemoryIngestConfigRepository(),
    )

    assert recovered == []
    assert racing_repo.expected_statuses == frozenset({"processing"})
    assert racing_repo.stale_before is not None
    assert repo.get_ingest_job(job_id).status == "processing"  # type: ignore[union-attr]
    assert repo.audit_events == []


class _CancelBeforeUpdateRepository:
    def __init__(self, repo: InMemoryDocumentRepository) -> None:
        self.repo = repo

    def get_ingest_job(self, job_id: str):
        return self.repo.get_ingest_job(job_id)

    def update_ingest_job(self, job_id: str, **_kwargs: object) -> IngestJobMutationResult:
        cancelled = self.repo.cancel_ingest_job(job_id, allowed_statuses=ACTIVE_STATUSES)
        return IngestJobMutationResult(job=cancelled.job, changed=False)


class _CapturingPostgresIngestJobRepository(PostgresIngestJobRepository):
    def __init__(self) -> None:
        super().__init__("postgresql://unused")
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def _execute_all(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        self.queries.append((query, params))
        now = datetime.now(UTC)
        return [
            {
                "id": "job-1",
                "doc_id": "doc-1",
                "retry_of_job_id": None,
                "origin": "upload",
                "status": "processing",
                "progress_pct": 40,
                "stage_progress": None,
                "attempt_count": 1,
                "last_heartbeat_at": now,
                "run_token": "worker-1",
                "warnings": [],
                "parser_provenance": None,
                "error_code": None,
                "error_message_safe": None,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
                "document_title": "Report.pdf",
                "group_path": "/ops",
                "clearance_level": "NATO_RESTRICTED",
                "uploaded_by": "user-1",
                "total": 2,
            }
        ]


class _CapturingPostgresIngestSummaryRepository(PostgresIngestJobRepository):
    def __init__(self) -> None:
        super().__init__("postgresql://unused")
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def _execute_all(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        self.queries.append((query, params))
        return [
            {"dimension": "metric", "name": "total", "value": 4},
            {"dimension": "metric", "name": "active", "value": 1},
            {"dimension": "metric", "name": "needs_attention", "value": 2},
            {"dimension": "status", "name": "complete", "value": 3},
            {"dimension": "status", "name": "failed", "value": 1},
            {"dimension": "stage", "name": "complete", "value": 3},
            {"dimension": "stage", "name": "failed", "value": 1},
            {"dimension": "origin", "name": "upload", "value": 4},
        ]


class _HeartbeatBeforeMaintenanceRepository:
    def __init__(self, repo: InMemoryDocumentRepository) -> None:
        self.repo = repo
        self.expected_statuses: frozenset[str] | None = None
        self.stale_before: datetime | None = None

    def update_ingest_job(self, job_id: str, **kwargs: object) -> IngestJobMutationResult:
        self.expected_statuses = kwargs.get("expected_statuses")  # type: ignore[assignment]
        self.stale_before = kwargs.get("stale_before")  # type: ignore[assignment]
        self.repo.heartbeat_ingest_job(job_id)
        return self.repo.update_ingest_job(job_id, **kwargs)  # type: ignore[arg-type]


class _MaintenanceControl:
    def apply(self, _worker_concurrency: int):
        return SimpleNamespace(active_job_ids=frozenset())


def _repository_with_job(*, status: str) -> tuple[InMemoryDocumentRepository, str, str]:
    repo = InMemoryDocumentRepository()
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
