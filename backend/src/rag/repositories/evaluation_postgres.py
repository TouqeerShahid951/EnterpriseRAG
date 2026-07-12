"""PostgreSQL evaluation repository."""

from __future__ import annotations

import json
from typing import Any

from ..schemas.evaluations import EvaluationCase
from ..shared.contracts.clearance import normalize_clearance_level
from .evaluation_models import (
    EvaluationCaseResultRecord,
    EvaluationDatasetRecord,
    EvaluationRunRecord,
    _RUN_JSON_FIELDS,
    _RUN_UPDATABLE_FIELDS,
)
from .postgres import PostgresConnectionMixin


class PostgresEvaluationRepository(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._ensure_tables()

    def create_dataset(self, **kwargs: Any) -> EvaluationDatasetRecord:
        row = self._execute_one(
            """
            INSERT INTO rag_evaluation_datasets (
                name, description, source_format, cases_json, metadata_json, created_by
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::uuid)
            RETURNING *
            """,
            (
                kwargs["name"],
                kwargs.get("description"),
                kwargs["source_format"],
                _dump_cases(kwargs["cases"]),
                json.dumps(kwargs.get("metadata") or {}),
                kwargs.get("created_by"),
            ),
        )
        return dataset_from_row(row)

    def list_datasets(self) -> list[EvaluationDatasetRecord]:
        return [dataset_from_row(row) for row in self._execute_all("SELECT * FROM rag_evaluation_datasets ORDER BY created_at DESC")]

    def get_dataset(self, dataset_id: str) -> EvaluationDatasetRecord | None:
        row = self._execute_optional("SELECT * FROM rag_evaluation_datasets WHERE id = %s", (dataset_id,))
        return dataset_from_row(row) if row else None

    def create_run(self, **kwargs: Any) -> EvaluationRunRecord:
        row = self._execute_one(
            """
            INSERT INTO rag_evaluation_runs (
                dataset_id, user_id, permission_version, user_email, account_type, group_paths, clearance_level,
                group_path, document_ids, selected_case_ids, rag_config_snapshot, case_count, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, NOW() + (%s * INTERVAL '1 day'))
            RETURNING *
            """,
            (
                kwargs["dataset_id"],
                kwargs["user_id"],
                kwargs["permission_version"],
                kwargs["user_email"],
                kwargs["account_type"],
                json.dumps(kwargs["group_paths"]),
                normalize_clearance_level(kwargs.get("clearance_level")),
                kwargs["group_path"],
                json.dumps(kwargs["document_ids"]),
                json.dumps(kwargs["selected_case_ids"]),
                json.dumps(kwargs["rag_config_snapshot"]),
                kwargs["case_count"],
                kwargs["retention_days"],
            ),
        )
        return run_from_row(row)

    def list_runs(self) -> list[EvaluationRunRecord]:
        return [run_from_row(row) for row in self._execute_all("SELECT * FROM rag_evaluation_runs ORDER BY created_at DESC")]

    def get_run(self, run_id: str) -> EvaluationRunRecord | None:
        row = self._execute_optional("SELECT * FROM rag_evaluation_runs WHERE id = %s", (run_id,))
        return run_from_row(row) if row else None

    def update_run(self, run_id: str, changes: dict[str, Any]) -> EvaluationRunRecord | None:
        unknown = set(changes) - _RUN_UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"unsupported evaluation run fields: {', '.join(sorted(unknown))}")
        if not changes:
            return self.get_run(run_id)
        assignments: list[str] = []
        values: list[Any] = []
        for field, value in changes.items():
            assignments.append(f"{field} = %s::jsonb" if field in _RUN_JSON_FIELDS else f"{field} = %s")
            values.append(json.dumps(value) if field in _RUN_JSON_FIELDS and value is not None else value)
        assignments.append("updated_at = NOW()")
        row = self._execute_optional(
            f"UPDATE rag_evaluation_runs SET {', '.join(assignments)} WHERE id = %s RETURNING *",
            (*values, run_id),
        )
        return run_from_row(row) if row else None

    def start_attempt(self, run_id: str) -> tuple[EvaluationRunRecord | None, bool]:
        row = self._execute_optional(
            """
            UPDATE rag_evaluation_runs
            SET status = 'running', stage = 'running', progress_pct = 0,
                attempt_count = attempt_count + 1,
                started_at = COALESCE(started_at, NOW()),
                last_heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE id = %s AND status = 'queued' AND attempt_count < max_attempts
            RETURNING *
            """,
            (run_id,),
        )
        if row:
            return run_from_row(row), True
        return self.get_run(run_id), False

    def heartbeat(self, run_id: str) -> EvaluationRunRecord | None:
        row = self._execute_optional(
            "UPDATE rag_evaluation_runs SET last_heartbeat_at = NOW(), updated_at = NOW() WHERE id = %s RETURNING *",
            (run_id,),
        )
        return run_from_row(row) if row else None

    def clear_case_results(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM rag_evaluation_case_results WHERE run_id = %s", (run_id,))

    def add_case_result(self, **kwargs: Any) -> EvaluationCaseResultRecord:
        row = self._execute_one(
            """
            INSERT INTO rag_evaluation_case_results (
                run_id, case_id, case_index, question, status, passed, primary_failure_stage,
                failure_stages, checks_json, answer, sources_json, diagnostic_json, trace_id,
                node_timings_json, faithfulness_score, faithfulness_status, unfounded_claims,
                degraded, degraded_reason, latency_ms, error_message_safe
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s,
                %s::jsonb, %s, %s, %s::jsonb,
                %s, %s, %s, %s
            )
            ON CONFLICT (run_id, case_id) DO UPDATE SET
                case_index = EXCLUDED.case_index,
                question = EXCLUDED.question,
                status = EXCLUDED.status,
                passed = EXCLUDED.passed,
                primary_failure_stage = EXCLUDED.primary_failure_stage,
                failure_stages = EXCLUDED.failure_stages,
                checks_json = EXCLUDED.checks_json,
                answer = EXCLUDED.answer,
                sources_json = EXCLUDED.sources_json,
                diagnostic_json = EXCLUDED.diagnostic_json,
                trace_id = EXCLUDED.trace_id,
                node_timings_json = EXCLUDED.node_timings_json,
                faithfulness_score = EXCLUDED.faithfulness_score,
                faithfulness_status = EXCLUDED.faithfulness_status,
                unfounded_claims = EXCLUDED.unfounded_claims,
                degraded = EXCLUDED.degraded,
                degraded_reason = EXCLUDED.degraded_reason,
                latency_ms = EXCLUDED.latency_ms,
                error_message_safe = EXCLUDED.error_message_safe
            RETURNING *
            """,
            (
                kwargs["run_id"],
                kwargs["case_id"],
                kwargs["case_index"],
                kwargs["question"],
                kwargs["status"],
                kwargs["passed"],
                kwargs.get("primary_failure_stage"),
                json.dumps(kwargs.get("failure_stages", [])),
                json.dumps(kwargs.get("checks_json", {})),
                kwargs.get("answer", ""),
                json.dumps(kwargs.get("sources_json", [])),
                json.dumps(kwargs.get("diagnostic_json", {})),
                kwargs.get("trace_id"),
                json.dumps(kwargs.get("node_timings_json", [])),
                kwargs.get("faithfulness_score"),
                kwargs.get("faithfulness_status"),
                json.dumps(kwargs.get("unfounded_claims", [])),
                kwargs.get("degraded", False),
                kwargs.get("degraded_reason"),
                kwargs.get("latency_ms", 0),
                kwargs.get("error_message_safe"),
            ),
        )
        return case_result_from_row(row)

    def list_case_results(self, run_id: str) -> list[EvaluationCaseResultRecord]:
        return [
            case_result_from_row(row)
            for row in self._execute_all(
                "SELECT * FROM rag_evaluation_case_results WHERE run_id = %s ORDER BY case_index",
                (run_id,),
            )
        ]

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(EVALUATION_SCHEMA_SQL)


def dataset_from_row(row: dict[str, Any]) -> EvaluationDatasetRecord:
    return EvaluationDatasetRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]) if row.get("description") else None,
        source_format=str(row["source_format"]),
        cases=tuple(EvaluationCase.model_validate(item) for item in _json_list(row.get("cases_json")) if isinstance(item, dict)),
        metadata=_json_object(row.get("metadata_json")),
        created_by=str(row["created_by"]) if row.get("created_by") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def run_from_row(row: dict[str, Any]) -> EvaluationRunRecord:
    return EvaluationRunRecord(
        id=str(row["id"]),
        dataset_id=str(row["dataset_id"]),
        user_id=str(row["user_id"]),
        permission_version=int(row["permission_version"]),
        user_email=str(row["user_email"]),
        account_type=str(row["account_type"]),
        group_paths=tuple(str(item) for item in _json_list(row.get("group_paths"))),
        clearance_level=normalize_clearance_level(row.get("clearance_level")),
        group_path=str(row["group_path"]) if row.get("group_path") else None,
        document_ids=tuple(str(item) for item in _json_list(row.get("document_ids"))),
        selected_case_ids=tuple(str(item) for item in _json_list(row.get("selected_case_ids"))),
        rag_config_snapshot=_json_object(row.get("rag_config_snapshot")),
        status=str(row["status"]),  # type: ignore[arg-type]
        stage=str(row["stage"]),
        progress_pct=int(row["progress_pct"]),
        case_count=int(row["case_count"]),
        completed_count=int(row["completed_count"]),
        passed_count=int(row["passed_count"]),
        failed_count=int(row["failed_count"]),
        summary_json=_json_object(row.get("summary_json")),
        error_code=str(row["error_code"]) if row.get("error_code") else None,
        error_message_safe=str(row["error_message_safe"]) if row.get("error_message_safe") else None,
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        cancellation_requested=bool(row["cancellation_requested"]),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        last_heartbeat_at=row.get("last_heartbeat_at"),
        expires_at=row.get("expires_at"),
    )


def case_result_from_row(row: dict[str, Any]) -> EvaluationCaseResultRecord:
    return EvaluationCaseResultRecord(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        case_id=str(row["case_id"]),
        case_index=int(row["case_index"]),
        question=str(row["question"]),
        status=str(row["status"]),
        passed=bool(row["passed"]),
        primary_failure_stage=str(row["primary_failure_stage"]) if row.get("primary_failure_stage") else None,
        failure_stages=tuple(str(item) for item in _json_list(row.get("failure_stages"))),
        checks_json=_json_object(row.get("checks_json")),
        answer=str(row["answer"] or ""),
        sources_json=tuple(dict(item) for item in _json_object_list(row.get("sources_json"))),
        diagnostic_json=_json_object(row.get("diagnostic_json")),
        trace_id=str(row["trace_id"]) if row.get("trace_id") else None,
        node_timings_json=tuple(dict(item) for item in _json_object_list(row.get("node_timings_json"))),
        faithfulness_score=float(row["faithfulness_score"]) if row.get("faithfulness_score") is not None else None,
        faithfulness_status=str(row["faithfulness_status"]) if row.get("faithfulness_status") else None,
        unfounded_claims=tuple(str(item) for item in _json_list(row.get("unfounded_claims"))),
        degraded=bool(row["degraded"]),
        degraded_reason=str(row["degraded_reason"]) if row.get("degraded_reason") else None,
        latency_ms=int(row["latency_ms"]),
        error_message_safe=str(row["error_message_safe"]) if row.get("error_message_safe") else None,
        created_at=row.get("created_at"),
    )


def _dump_cases(cases: list[EvaluationCase]) -> str:
    return json.dumps([case.model_dump(mode="json") for case in cases])


def _load_json(value: object, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, str):
        return json.loads(value)
    return value


def _json_list(value: object) -> list[Any]:
    loaded = _load_json(value, [])
    return list(loaded) if isinstance(loaded, list) else []


def _json_object_list(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in _json_list(value) if isinstance(item, dict)]


def _json_object(value: object) -> dict[str, Any]:
    loaded = _load_json(value, {})
    return dict(loaded) if isinstance(loaded, dict) else {}


EVALUATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rag_evaluation_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT NULL,
    source_format TEXT NOT NULL,
    cases_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT rag_evaluation_datasets_name_not_blank CHECK (length(btrim(name)) > 0),
    CONSTRAINT rag_evaluation_datasets_cases_array CHECK (jsonb_typeof(cases_json) = 'array')
);

CREATE TABLE IF NOT EXISTS rag_evaluation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL REFERENCES rag_evaluation_datasets(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_version INTEGER NOT NULL,
    user_email TEXT NOT NULL,
    account_type TEXT NOT NULL,
    group_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED',
    group_path TEXT NULL,
    document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_case_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    rag_config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    progress_pct INTEGER NOT NULL DEFAULT 0,
    case_count INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0,
    passed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
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
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT rag_evaluation_runs_status_known CHECK (status IN ('queued', 'running', 'complete', 'partial', 'failed', 'cancelled')),
    CONSTRAINT rag_evaluation_runs_progress_valid CHECK (progress_pct BETWEEN 0 AND 100),
    CONSTRAINT rag_evaluation_runs_counts_valid CHECK (
        case_count >= 0 AND completed_count >= 0 AND passed_count >= 0 AND failed_count >= 0
    )
);

ALTER TABLE rag_evaluation_runs
    ADD COLUMN IF NOT EXISTS clearance_level TEXT NOT NULL DEFAULT 'NATO_RESTRICTED';

CREATE TABLE IF NOT EXISTS rag_evaluation_case_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES rag_evaluation_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    case_index INTEGER NOT NULL,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    passed BOOLEAN NOT NULL DEFAULT FALSE,
    primary_failure_stage TEXT NULL,
    failure_stages JSONB NOT NULL DEFAULT '[]'::jsonb,
    checks_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    answer TEXT NOT NULL DEFAULT '',
    sources_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    diagnostic_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    trace_id TEXT NULL,
    node_timings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    faithfulness_score DOUBLE PRECISION NULL,
    faithfulness_status TEXT NULL,
    unfounded_claims JSONB NOT NULL DEFAULT '[]'::jsonb,
    degraded BOOLEAN NOT NULL DEFAULT FALSE,
    degraded_reason TEXT NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    error_message_safe TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT rag_evaluation_case_results_status_known CHECK (status IN ('ok', 'error')),
    CONSTRAINT rag_evaluation_case_results_latency_nonnegative CHECK (latency_ms >= 0),
    CONSTRAINT rag_evaluation_case_results_failure_stages_array CHECK (jsonb_typeof(failure_stages) = 'array')
);

CREATE INDEX IF NOT EXISTS rag_evaluation_datasets_created_idx
    ON rag_evaluation_datasets (created_at DESC);
CREATE INDEX IF NOT EXISTS rag_evaluation_runs_created_idx
    ON rag_evaluation_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS rag_evaluation_runs_active_idx
    ON rag_evaluation_runs (status, updated_at)
    WHERE status NOT IN ('complete', 'partial', 'failed', 'cancelled');
CREATE UNIQUE INDEX IF NOT EXISTS rag_evaluation_case_results_run_case_uidx
    ON rag_evaluation_case_results (run_id, case_id);
"""
