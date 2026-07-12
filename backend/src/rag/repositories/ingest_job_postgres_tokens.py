"""Run-token guards for PostgreSQL ingestion jobs."""

from __future__ import annotations

from .ingest_job_models import IngestJobRecord


def _run_token_can_update(
    current: IngestJobRecord,
    *,
    run_token: str | None,
    next_status: str,
) -> bool:
    if current.run_token is not None:
        return current.run_token == run_token
    if run_token is None:
        return True
    return current.status == "queued" and next_status == "processing"


def _next_run_token(
    current: IngestJobRecord,
    *,
    run_token: str | None,
    next_status: str,
) -> str | None:
    if next_status != "processing":
        return None
    if current.run_token is None and run_token is not None:
        return run_token
    return current.run_token
