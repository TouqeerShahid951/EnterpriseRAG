"""In-memory artifact-generation job repository."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4

from ...shared.contracts.clearance import normalize_clearance_level
from ..job_models import (
    ACTIVE_ARTIFACT_JOB_STATUSES,
    DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT,
    TERMINAL_ARTIFACT_JOB_STATUSES,
    ArtifactJobRecord,
    _clears_run_token,
    _is_explicit_retry,
    _validate_changes,
    _validate_expiry_query,
)
from ..types import ArtifactJobStatus


class InMemoryArtifactJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, ArtifactJobRecord] = {}
        self._lock = RLock()

    def create_job(self, **kwargs: Any) -> ArtifactJobRecord:
        with self._lock:
            existing = self.get_job_by_client_request(
                user_id=str(kwargs["user_id"]),
                permission_version=int(kwargs["permission_version"]),
                client_request_id=str(kwargs["client_request_id"]),
            )
            if existing is not None:
                return existing
            now = datetime.now(UTC)
            record = ArtifactJobRecord(
                id=str(uuid4()),
                client_request_id=str(kwargs["client_request_id"]),
                user_id=str(kwargs["user_id"]),
                permission_version=int(kwargs["permission_version"]),
                user_email=str(kwargs["user_email"]),
                account_type=str(kwargs["account_type"]),
                group_paths=tuple(str(item) for item in kwargs["group_paths"]),
                clearance_level=normalize_clearance_level(
                    kwargs.get("clearance_level")
                ),
                session_id=str(kwargs["session_id"]),
                trace_id=str(kwargs["trace_id"]),
                original_request=str(kwargs["original_request"]),
                requested_formats=tuple(
                    str(item) for item in kwargs["requested_formats"]
                ),
                group_path=str(kwargs["group_path"])
                if kwargs.get("group_path")
                else None,
                document_ids=tuple(str(item) for item in kwargs["document_ids"]),
                conversation_context=tuple(
                    dict(item) for item in kwargs["conversation_context"]
                ),
                clarifications={},
                status="queued",
                stage="queued",
                progress_pct=0,
                stage_progress=None,
                plan_json=None,
                evidence_manifest_json=None,
                content_spec_json=None,
                validation_results_json=None,
                stage_timings_json={},
                model_versions={},
                prompt_versions={},
                errors_json=(),
                error_code=None,
                error_message_safe=None,
                attempt_count=0,
                max_attempts=3,
                cancellation_requested=False,
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
                last_heartbeat_at=None,
                run_token=None,
                expires_at=now + timedelta(days=int(kwargs["retention_days"])),
            )
            self._jobs[record.id] = record
            return record

    def get_job(self, job_id: str) -> ArtifactJobRecord | None:
        return self._jobs.get(job_id)

    def get_job_by_client_request(
        self, *, user_id: str, permission_version: int, client_request_id: str
    ) -> ArtifactJobRecord | None:
        return next(
            (
                job
                for job in self._jobs.values()
                if job.user_id == user_id
                and job.permission_version == permission_version
                and job.client_request_id == client_request_id
            ),
            None,
        )

    def update_job(
        self, job_id: str, changes: dict[str, object]
    ) -> ArtifactJobRecord | None:
        _validate_changes(changes)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in TERMINAL_ARTIFACT_JOB_STATUSES and not _is_explicit_retry(
                job, changes
            ):
                return job
            normalized_changes = dict(changes)
            if _clears_run_token(normalized_changes):
                normalized_changes["run_token"] = None
            updated = replace(job, **normalized_changes, updated_at=datetime.now(UTC))
            self._jobs[job_id] = updated
            return updated

    def transition_job(
        self,
        job_id: str,
        *,
        run_token: str,
        changes: dict[str, object],
        expected_statuses: Collection[ArtifactJobStatus] | None = None,
    ) -> ArtifactJobRecord | None:
        _validate_changes(changes)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if (
                job.status in TERMINAL_ARTIFACT_JOB_STATUSES
                or job.run_token != run_token
            ):
                return None
            if expected_statuses is not None and job.status not in expected_statuses:
                return None
            normalized_changes = dict(changes)
            if _clears_run_token(normalized_changes):
                normalized_changes["run_token"] = None
            updated = replace(job, **normalized_changes, updated_at=datetime.now(UTC))
            self._jobs[job_id] = updated
            return updated

    def start_attempt(
        self,
        job_id: str,
        *,
        run_token: str | None = None,
        stale_before: datetime | None = None,
    ) -> tuple[ArtifactJobRecord | None, bool]:
        selected_token = run_token or str(uuid4())
        selected_stale_before = (
            stale_before or datetime.now(UTC) - DEFAULT_ARTIFACT_JOB_LEASE_TIMEOUT
        )
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None, False
            if (
                job.run_token == selected_token
                and job.status in ACTIVE_ARTIFACT_JOB_STATUSES
            ):
                return job, True
            is_new_attempt = (
                job.status == "queued" and job.attempt_count < job.max_attempts
            )
            is_stale_attempt = job.status in ACTIVE_ARTIFACT_JOB_STATUSES and (
                job.last_heartbeat_at is None
                or job.last_heartbeat_at <= selected_stale_before
            )
            if is_stale_attempt and job.attempt_count >= job.max_attempts:
                now = datetime.now(UTC)
                failed = replace(
                    job,
                    status="failed",
                    stage="failed",
                    progress_pct=100,
                    stage_progress=None,
                    error_code="artifact_attempts_exhausted",
                    error_message_safe="Document generation exhausted its retry limit.",
                    completed_at=now,
                    run_token=None,
                    updated_at=now,
                )
                self._jobs[job_id] = failed
                return failed, False
            if not is_new_attempt and not is_stale_attempt:
                return job, False
            now = datetime.now(UTC)
            updated = replace(
                job,
                status="planning",
                stage="planning",
                progress_pct=5,
                stage_progress=None,
                attempt_count=job.attempt_count + 1,
                started_at=job.started_at or now,
                last_heartbeat_at=now,
                run_token=selected_token,
                updated_at=now,
            )
            self._jobs[job_id] = updated
            return updated, True

    def heartbeat(
        self, job_id: str, *, run_token: str | None = None
    ) -> ArtifactJobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if (
                job is None
                or not run_token
                or job.run_token != run_token
                or job.status not in ACTIVE_ARTIFACT_JOB_STATUSES
            ):
                return None
            now = datetime.now(UTC)
            updated = replace(job, last_heartbeat_at=now, updated_at=now)
            self._jobs[job_id] = updated
            return updated

    def list_expired_jobs(
        self,
        *,
        expires_before: datetime,
        limit: int = 100,
    ) -> list[ArtifactJobRecord]:
        _validate_expiry_query(expires_before=expires_before, limit=limit)
        with self._lock:
            expired = (
                job
                for job in self._jobs.values()
                if job.expires_at is not None and job.expires_at <= expires_before
            )
            return sorted(expired, key=lambda job: (job.expires_at, job.id))[:limit]

    def delete_expired_job(
        self,
        job_id: str,
        *,
        expires_before: datetime,
    ) -> bool:
        _validate_expiry_query(expires_before=expires_before, limit=1)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.expires_at is None or job.expires_at > expires_before:
                return False
            del self._jobs[job_id]
            return True
