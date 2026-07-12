"""Ingestion-job repository contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class IngestJobRecord:
    id: str
    doc_id: str
    retry_of_job_id: str | None
    origin: str
    status: str
    progress_pct: int
    stage_progress: dict[str, Any] | None
    attempt_count: int
    last_heartbeat_at: datetime | None
    warnings: tuple[str, ...]
    parser_provenance: dict[str, Any] | None
    error_code: str | None
    error_message_safe: str | None
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None
    run_token: str | None = None


@dataclass(frozen=True)
class IngestJobMutationResult:
    job: IngestJobRecord | None
    changed: bool


@dataclass(frozen=True)
class IngestAttemptResult:
    job: IngestJobRecord | None
    claimed: bool


@dataclass(frozen=True)
class IngestJobCancellationResult:
    job: IngestJobRecord | None
    changed: bool
    review_items_closed: int


@runtime_checkable
class IngestJobRepository(Protocol):
    """Persistence boundary for ingestion-job lifecycle state."""

    def create_ingest_job(
        self,
        *,
        doc_id: str,
        status: str,
        progress_pct: int,
        origin: str = "unknown",
        retry_of_job_id: str | None = None,
    ) -> IngestJobRecord: ...

    def get_ingest_job(self, job_id: str) -> IngestJobRecord | None: ...

    def list_ingest_jobs(self) -> list[IngestJobRecord]: ...

    def get_active_ingest_job_for_document(
        self,
        doc_id: str,
    ) -> IngestJobRecord | None: ...

    def update_ingest_job(
        self,
        job_id: str,
        *,
        status: str,
        progress_pct: int,
        stage_progress: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
        expected_statuses: frozenset[str] | None = None,
        stale_before: datetime | None = None,
        run_token: str | None = None,
    ) -> IngestJobMutationResult: ...

    def requeue_stale_ingest_job(
        self,
        job_id: str,
        *,
        stale_before: datetime,
        max_attempts: int,
    ) -> IngestJobRecord | None: ...

    def start_ingest_attempt(
        self,
        job_id: str,
        *,
        max_attempts: int,
        stale_after_seconds: int = 120,
        run_token: str | None = None,
    ) -> IngestAttemptResult: ...

    def heartbeat_ingest_job(
        self,
        job_id: str,
        *,
        run_token: str | None = None,
    ) -> IngestJobMutationResult: ...

    def record_ingest_parser_provenance(
        self,
        job_id: str,
        *,
        provenance: dict[str, Any],
        run_token: str | None = None,
    ) -> IngestJobRecord | None: ...

    def cancel_ingest_job(
        self,
        job_id: str,
        *,
        allowed_statuses: frozenset[str],
    ) -> IngestJobCancellationResult: ...


__all__ = [
    "IngestAttemptResult",
    "IngestJobCancellationResult",
    "IngestJobMutationResult",
    "IngestJobRecord",
    "IngestJobRepository",
]
