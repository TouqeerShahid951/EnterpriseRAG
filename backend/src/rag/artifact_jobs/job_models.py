"""Artifact-generation job repository contracts and records."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from .types import ArtifactJobStatus


TERMINAL_ARTIFACT_JOB_STATUSES = frozenset(
    {"complete", "partial", "failed", "cancelled"}
)
ACTIVE_ARTIFACT_JOB_STATUSES = frozenset(
    {"planning", "retrieving", "composing", "validating", "rendering"}
)
DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT = timedelta(seconds=90)


@dataclass(frozen=True)
class ArtifactJobRecord:
    id: str
    client_request_id: str
    user_id: str
    permission_version: int
    user_email: str
    account_type: str
    group_paths: tuple[str, ...]
    clearance_level: str
    session_id: str
    trace_id: str
    original_request: str
    requested_formats: tuple[str, ...]
    group_path: str | None
    document_ids: tuple[str, ...]
    conversation_context: tuple[dict[str, object], ...]
    clarifications: dict[str, str]
    status: ArtifactJobStatus
    stage: str
    progress_pct: int
    stage_progress: dict[str, object] | None
    plan_json: dict[str, object] | None
    evidence_manifest_json: dict[str, object] | None
    content_spec_json: dict[str, object] | None
    validation_results_json: dict[str, object] | None
    stage_timings_json: dict[str, object]
    model_versions: dict[str, str]
    prompt_versions: dict[str, str]
    errors_json: tuple[dict[str, object], ...]
    error_code: str | None
    error_message_safe: str | None
    attempt_count: int
    max_attempts: int
    cancellation_requested: bool
    created_at: datetime | None
    updated_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    last_heartbeat_at: datetime | None
    run_token: str | None
    expires_at: datetime | None


class ArtifactJobRepository(Protocol):
    def create_job(
        self,
        *,
        client_request_id: str,
        user_id: str,
        permission_version: int,
        user_email: str,
        account_type: str,
        group_paths: list[str],
        clearance_level: str,
        session_id: str,
        trace_id: str,
        original_request: str,
        requested_formats: list[str],
        group_path: str | None,
        document_ids: list[str],
        conversation_context: list[dict[str, object]],
        retention_days: int,
    ) -> ArtifactJobRecord: ...

    def get_job(self, job_id: str) -> ArtifactJobRecord | None: ...
    def get_job_by_client_request(
        self, *, user_id: str, permission_version: int, client_request_id: str
    ) -> ArtifactJobRecord | None: ...
    def update_job(
        self, job_id: str, changes: dict[str, object]
    ) -> ArtifactJobRecord | None: ...
    def transition_job(
        self,
        job_id: str,
        *,
        run_token: str,
        changes: dict[str, object],
        expected_statuses: Collection[ArtifactJobStatus] | None = None,
    ) -> ArtifactJobRecord | None: ...
    def start_attempt(
        self,
        job_id: str,
        *,
        run_token: str | None = None,
        stale_before: datetime | None = None,
    ) -> tuple[ArtifactJobRecord | None, bool]: ...
    def heartbeat(
        self, job_id: str, *, run_token: str | None = None
    ) -> ArtifactJobRecord | None: ...
    def list_expired_jobs(
        self,
        *,
        expires_before: datetime,
        limit: int = 100,
    ) -> list[ArtifactJobRecord]: ...
    def delete_expired_job(
        self,
        job_id: str,
        *,
        expires_before: datetime,
    ) -> bool: ...


_UPDATABLE_FIELDS = {
    "status",
    "stage",
    "progress_pct",
    "stage_progress",
    "clarifications",
    "plan_json",
    "evidence_manifest_json",
    "content_spec_json",
    "validation_results_json",
    "stage_timings_json",
    "model_versions",
    "prompt_versions",
    "errors_json",
    "error_code",
    "error_message_safe",
    "attempt_count",
    "cancellation_requested",
    "started_at",
    "completed_at",
    "last_heartbeat_at",
}
_JSON_FIELDS = {
    "clarifications",
    "plan_json",
    "evidence_manifest_json",
    "content_spec_json",
    "validation_results_json",
    "stage_timings_json",
    "stage_progress",
    "model_versions",
    "prompt_versions",
    "errors_json",
}


def _validate_changes(changes: dict[str, object]) -> None:
    unknown = set(changes) - _UPDATABLE_FIELDS
    if unknown:
        raise ValueError(
            f"unsupported artifact job fields: {', '.join(sorted(unknown))}"
        )


def _is_explicit_retry(job: ArtifactJobRecord, changes: dict[str, object]) -> bool:
    return (
        job.status in {"failed", "partial", "cancelled"}
        and changes.get("status") == "queued"
        and changes.get("completed_at", object()) is None
        and changes.get("last_heartbeat_at", object()) is None
    )


def _clears_run_token(changes: dict[str, object]) -> bool:
    return changes.get("status") in {
        *TERMINAL_ARTIFACT_JOB_STATUSES,
        "needs_input",
        "queued",
    }


def _validate_expiry_query(*, expires_before: datetime, limit: int) -> None:
    if expires_before.tzinfo is None or expires_before.utcoffset() is None:
        raise ValueError("expires_before must be timezone-aware")
    if limit < 1:
        raise ValueError("limit must be positive")
