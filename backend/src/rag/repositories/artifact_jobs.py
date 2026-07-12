"""Persistence adapters for asynchronous artifact-generation jobs."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
import json
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from ..core.config import settings
from ..schemas.query import ArtifactJobStatus
from ..shared.contracts.clearance import normalize_clearance_level
from .postgres import PostgresConnectionMixin


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


class PostgresArtifactJobRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._ensure_tables()

    def create_job(self, **kwargs: Any) -> ArtifactJobRecord:
        row = self._execute_one(
            """
            INSERT INTO artifact_generation_jobs (
                client_request_id, user_id, permission_version, user_email, account_type,
                group_paths, clearance_level, session_id, trace_id, original_request, requested_formats,
                group_path, document_ids, conversation_context, expires_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb,
                %s, %s::jsonb, %s::jsonb, NOW() + (%s * INTERVAL '1 day')
            )
            ON CONFLICT (user_id, permission_version, client_request_id)
            DO UPDATE SET updated_at = artifact_generation_jobs.updated_at
            RETURNING *
            """,
            (
                kwargs["client_request_id"],
                kwargs["user_id"],
                kwargs["permission_version"],
                kwargs["user_email"],
                kwargs["account_type"],
                json.dumps(kwargs["group_paths"]),
                normalize_clearance_level(kwargs.get("clearance_level")),
                kwargs["session_id"],
                kwargs["trace_id"],
                kwargs["original_request"],
                json.dumps(kwargs["requested_formats"]),
                kwargs["group_path"],
                json.dumps(kwargs["document_ids"]),
                json.dumps(kwargs["conversation_context"]),
                kwargs["retention_days"],
            ),
        )
        return artifact_job_from_row(row)

    def get_job(self, job_id: str) -> ArtifactJobRecord | None:
        row = self._execute_optional(
            "SELECT * FROM artifact_generation_jobs WHERE id = %s", (job_id,)
        )
        return artifact_job_from_row(row) if row else None

    def get_job_by_client_request(
        self, *, user_id: str, permission_version: int, client_request_id: str
    ) -> ArtifactJobRecord | None:
        row = self._execute_optional(
            """
            SELECT * FROM artifact_generation_jobs
            WHERE user_id = %s AND permission_version = %s AND client_request_id = %s
            """,
            (user_id, permission_version, client_request_id),
        )
        return artifact_job_from_row(row) if row else None

    def update_job(
        self, job_id: str, changes: dict[str, object]
    ) -> ArtifactJobRecord | None:
        _validate_changes(changes)
        if not changes:
            return self.get_job(job_id)
        current = self.get_job(job_id)
        if current is None:
            return None
        explicit_retry = _is_explicit_retry(current, changes)
        if current.status in TERMINAL_ARTIFACT_JOB_STATUSES and not explicit_retry:
            return current
        assignments: list[str] = []
        values: list[object] = []
        for field, value in changes.items():
            assignments.append(
                f"{field} = %s::jsonb" if field in _JSON_FIELDS else f"{field} = %s"
            )
            values.append(
                json.dumps(value)
                if field in _JSON_FIELDS and value is not None
                else value
            )
        if _clears_run_token(changes):
            assignments.append("run_token = NULL")
        assignments.append("updated_at = NOW()")
        status_guard = (
            "status IN ('failed', 'partial', 'cancelled')"
            if explicit_retry
            else "status NOT IN ('complete', 'partial', 'failed', 'cancelled')"
        )
        row = self._execute_optional(
            f"""
            UPDATE artifact_generation_jobs
            SET {", ".join(assignments)}
            WHERE id = %s AND {status_guard}
            RETURNING *
            """,
            (*values, job_id),
        )
        return artifact_job_from_row(row) if row else self.get_job(job_id)

    def transition_job(
        self,
        job_id: str,
        *,
        run_token: str,
        changes: dict[str, object],
        expected_statuses: Collection[ArtifactJobStatus] | None = None,
    ) -> ArtifactJobRecord | None:
        _validate_changes(changes)
        if not changes:
            current = self.get_job(job_id)
            if (
                current is None
                or current.run_token != run_token
                or current.status in TERMINAL_ARTIFACT_JOB_STATUSES
                or (
                    expected_statuses is not None
                    and current.status not in expected_statuses
                )
            ):
                return None
            return current
        assignments: list[str] = []
        values: list[object] = []
        for field, value in changes.items():
            assignments.append(
                f"{field} = %s::jsonb" if field in _JSON_FIELDS else f"{field} = %s"
            )
            values.append(
                json.dumps(value)
                if field in _JSON_FIELDS and value is not None
                else value
            )
        if _clears_run_token(changes):
            assignments.append("run_token = NULL")
        assignments.append("updated_at = NOW()")
        status_clause = ""
        status_values: tuple[object, ...] = ()
        if expected_statuses is not None:
            selected_statuses = tuple(dict.fromkeys(expected_statuses))
            if not selected_statuses:
                return None
            status_clause = (
                f" AND status IN ({', '.join('%s' for _ in selected_statuses)})"
            )
            status_values = selected_statuses
        row = self._execute_optional(
            f"""
            UPDATE artifact_generation_jobs
            SET {", ".join(assignments)}
            WHERE id = %s AND run_token = %s
              AND status NOT IN ('complete', 'partial', 'failed', 'cancelled')
              {status_clause}
            RETURNING *
            """,
            (*values, job_id, run_token, *status_values),
        )
        return artifact_job_from_row(row) if row else None

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
        row = self._execute_optional(
            """
            UPDATE artifact_generation_jobs
            SET status = 'planning', stage = 'planning', progress_pct = 5,
                stage_progress = NULL,
                attempt_count = attempt_count + 1,
                started_at = COALESCE(started_at, NOW()),
                last_heartbeat_at = NOW(), run_token = %s, updated_at = NOW()
            WHERE id = %s AND (
                (status = 'queued' AND attempt_count < max_attempts)
                OR (
                    status IN ('planning', 'retrieving', 'composing', 'validating', 'rendering')
                    AND attempt_count < max_attempts
                    AND run_token IS DISTINCT FROM %s
                    AND (last_heartbeat_at IS NULL OR last_heartbeat_at <= %s)
                )
            )
            RETURNING *
            """,
            (selected_token, job_id, selected_token, selected_stale_before),
        )
        if row:
            return artifact_job_from_row(row), True
        current = self.get_job(job_id)
        if (
            current is not None
            and current.run_token == selected_token
            and current.status in ACTIVE_ARTIFACT_JOB_STATUSES
        ):
            return current, True
        failed = self._execute_optional(
            """
            UPDATE artifact_generation_jobs
            SET status = 'failed', stage = 'failed', progress_pct = 100,
                stage_progress = NULL,
                error_code = 'artifact_attempts_exhausted',
                error_message_safe = 'Document generation exhausted its retry limit.',
                completed_at = NOW(), run_token = NULL, updated_at = NOW()
            WHERE id = %s
              AND status IN ('planning', 'retrieving', 'composing', 'validating', 'rendering')
              AND attempt_count >= max_attempts
              AND (last_heartbeat_at IS NULL OR last_heartbeat_at <= %s)
            RETURNING *
            """,
            (job_id, selected_stale_before),
        )
        if failed:
            return artifact_job_from_row(failed), False
        return self.get_job(job_id), False

    def heartbeat(
        self, job_id: str, *, run_token: str | None = None
    ) -> ArtifactJobRecord | None:
        if not run_token:
            return None
        row = self._execute_optional(
            """
            UPDATE artifact_generation_jobs
            SET last_heartbeat_at = NOW(), updated_at = NOW()
            WHERE id = %s AND run_token = %s
              AND status IN ('planning', 'retrieving', 'composing', 'validating', 'rendering')
            RETURNING *
            """,
            (job_id, run_token),
        )
        return artifact_job_from_row(row) if row else None

    def list_expired_jobs(
        self,
        *,
        expires_before: datetime,
        limit: int = 100,
    ) -> list[ArtifactJobRecord]:
        _validate_expiry_query(expires_before=expires_before, limit=limit)
        rows = self._execute_all(
            """
            SELECT * FROM artifact_generation_jobs
            WHERE expires_at <= %s
            ORDER BY expires_at, id
            LIMIT %s
            """,
            (expires_before, limit),
        )
        return [artifact_job_from_row(row) for row in rows]

    def delete_expired_job(
        self,
        job_id: str,
        *,
        expires_before: datetime,
    ) -> bool:
        _validate_expiry_query(expires_before=expires_before, limit=1)
        row = self._execute_optional(
            """
            DELETE FROM artifact_generation_jobs AS job
            WHERE job.id = %s
              AND job.expires_at <= %s
              AND NOT EXISTS (
                  SELECT 1 FROM generated_artifacts AS artifact
                  WHERE artifact.job_id = job.id
              )
            RETURNING job.id
            """,
            (job_id, expires_before),
        )
        return row is not None

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(ARTIFACT_JOB_SCHEMA_SQL)


def artifact_job_from_row(row: dict[str, Any]) -> ArtifactJobRecord:
    return ArtifactJobRecord(
        id=str(row["id"]),
        client_request_id=str(row["client_request_id"]),
        user_id=str(row["user_id"]),
        permission_version=int(row["permission_version"]),
        user_email=str(row["user_email"]),
        account_type=str(row["account_type"]),
        group_paths=tuple(_json_list(row.get("group_paths"))),
        clearance_level=normalize_clearance_level(row.get("clearance_level")),
        session_id=str(row["session_id"]),
        trace_id=str(row["trace_id"]),
        original_request=str(row["original_request"]),
        requested_formats=tuple(_json_list(row.get("requested_formats"))),
        group_path=str(row["group_path"]) if row.get("group_path") else None,
        document_ids=tuple(_json_list(row.get("document_ids"))),
        conversation_context=tuple(_json_object_list(row.get("conversation_context"))),
        clarifications={
            str(key): str(value)
            for key, value in _json_object(row.get("clarifications")).items()
        },
        status=str(row["status"]),  # type: ignore[arg-type]
        stage=str(row["stage"]),
        progress_pct=int(row["progress_pct"]),
        stage_progress=_optional_json_object(row.get("stage_progress")),
        plan_json=_optional_json_object(row.get("plan_json")),
        evidence_manifest_json=_optional_json_object(row.get("evidence_manifest_json")),
        content_spec_json=_optional_json_object(row.get("content_spec_json")),
        validation_results_json=_optional_json_object(
            row.get("validation_results_json")
        ),
        stage_timings_json=_json_object(row.get("stage_timings_json")),
        model_versions={
            str(key): str(value)
            for key, value in _json_object(row.get("model_versions")).items()
        },
        prompt_versions={
            str(key): str(value)
            for key, value in _json_object(row.get("prompt_versions")).items()
        },
        errors_json=tuple(_json_object_list(row.get("errors_json"))),
        error_code=str(row["error_code"]) if row.get("error_code") else None,
        error_message_safe=str(row["error_message_safe"])
        if row.get("error_message_safe")
        else None,
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        cancellation_requested=bool(row["cancellation_requested"]),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        last_heartbeat_at=row.get("last_heartbeat_at"),
        run_token=str(row["run_token"]) if row.get("run_token") else None,
        expires_at=row.get("expires_at"),
    )


def _load_json(value: object, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, str):
        return json.loads(value)
    return value


def _json_list(value: object) -> list[str]:
    loaded = _load_json(value, [])
    return [str(item) for item in loaded] if isinstance(loaded, list) else []


def _json_object_list(value: object) -> list[dict[str, object]]:
    loaded = _load_json(value, [])
    return (
        [dict(item) for item in loaded if isinstance(item, dict)]
        if isinstance(loaded, list)
        else []
    )


def _json_object(value: object) -> dict[str, object]:
    loaded = _load_json(value, {})
    return dict(loaded) if isinstance(loaded, dict) else {}


def _optional_json_object(value: object) -> dict[str, object] | None:
    return None if value is None else _json_object(value)


ARTIFACT_JOB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artifact_generation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_request_id TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_version INTEGER NOT NULL,
    user_email TEXT NOT NULL,
    account_type TEXT NOT NULL,
    group_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED',
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    original_request TEXT NOT NULL,
    requested_formats JSONB NOT NULL DEFAULT '[]'::jsonb,
    group_path TEXT NULL,
    document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    conversation_context JSONB NOT NULL DEFAULT '[]'::jsonb,
    clarifications JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    stage_progress JSONB NULL,
    plan_json JSONB NULL,
    evidence_manifest_json JSONB NULL,
    content_spec_json JSONB NULL,
    validation_results_json JSONB NULL,
    stage_timings_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    prompt_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    errors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_code TEXT NULL,
    error_message_safe TEXT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    last_heartbeat_at TIMESTAMPTZ NULL,
    run_token TEXT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT artifact_generation_jobs_status_known CHECK (
        status IN ('queued', 'planning', 'needs_input', 'retrieving', 'composing',
                   'validating', 'rendering', 'complete', 'partial', 'failed', 'cancelled')
    ),
    CONSTRAINT artifact_generation_jobs_progress_valid CHECK (progress_pct BETWEEN 0 AND 100),
    CONSTRAINT artifact_generation_jobs_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
    ),
    CONSTRAINT artifact_generation_jobs_formats_array CHECK (jsonb_typeof(requested_formats) = 'array'),
    CONSTRAINT artifact_generation_jobs_documents_array CHECK (jsonb_typeof(document_ids) = 'array')
);

ALTER TABLE artifact_generation_jobs
    ADD COLUMN IF NOT EXISTS clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED';
ALTER TABLE artifact_generation_jobs
    ADD COLUMN IF NOT EXISTS run_token TEXT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS artifact_generation_jobs_client_uidx
    ON artifact_generation_jobs (user_id, permission_version, client_request_id);
CREATE INDEX IF NOT EXISTS artifact_generation_jobs_user_created_idx
    ON artifact_generation_jobs (user_id, permission_version, created_at DESC);
CREATE INDEX IF NOT EXISTS artifact_generation_jobs_active_idx
    ON artifact_generation_jobs (status, updated_at)
    WHERE status NOT IN ('complete', 'partial', 'failed', 'cancelled');

ALTER TABLE artifact_generation_jobs
    ADD COLUMN IF NOT EXISTS validation_results_json JSONB NULL;
ALTER TABLE artifact_generation_jobs
    ADD COLUMN IF NOT EXISTS stage_timings_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE artifact_generation_jobs
    ADD COLUMN IF NOT EXISTS stage_progress JSONB NULL;
ALTER TABLE artifact_generation_jobs
    ADD COLUMN IF NOT EXISTS errors_json JSONB NOT NULL DEFAULT '[]'::jsonb;
"""


@lru_cache
def default_artifact_job_repository() -> ArtifactJobRepository:
    if settings.document_repository == "memory":
        return InMemoryArtifactJobRepository()
    return PostgresArtifactJobRepository(settings.database_url)


def get_artifact_job_repository() -> ArtifactJobRepository:
    return default_artifact_job_repository()
