"""PostgreSQL evaluation repository."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from ...shared.persistence import PostgresConnectionMixin
from rag.evaluations.schemas import EvaluationCase
from ...shared.contracts.clearance import normalize_clearance_level
from ..models import (
    DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT,
    EvaluationCaseClaim,
    EvaluationCaseCommit,
    EvaluationCaseExecutionRecord,
    EvaluationCaseResultRecord,
    EvaluationCaseResultPayload,
    EvaluationCaseTerminalStatus,
    EvaluationDatasetRecord,
    EvaluationRunRecord,
    _RUN_JSON_FIELDS,
    _RUN_UPDATABLE_FIELDS,
)
from ..scoring import summarize_results


_TERMINAL_RUN_STATUSES = frozenset({"complete", "partial", "failed", "cancelled"})
_EXHAUSTED_ERROR_CODE = "evaluation_case_attempts_exhausted"
_EXHAUSTED_ERROR_MESSAGE = "Evaluation case exhausted its retry limit."


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
        return [
            dataset_from_row(row)
            for row in self._execute_all(
                "SELECT * FROM rag_evaluation_datasets ORDER BY created_at DESC"
            )
        ]

    def get_dataset(self, dataset_id: str) -> EvaluationDatasetRecord | None:
        row = self._execute_optional(
            "SELECT * FROM rag_evaluation_datasets WHERE id = %s", (dataset_id,)
        )
        return dataset_from_row(row) if row else None

    def create_run(self, **kwargs: Any) -> EvaluationRunRecord:
        selected_case_ids = _validated_case_selection(kwargs)
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO rag_evaluation_runs (
                    dataset_id, user_id, permission_version, user_email, account_type,
                    group_paths, clearance_level, group_path, document_ids,
                    selected_case_ids, rag_config_snapshot, case_count, expires_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s, NOW() + (%s * INTERVAL '1 day')
                )
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
                    json.dumps(selected_case_ids),
                    json.dumps(kwargs["rag_config_snapshot"]),
                    kwargs["case_count"],
                    kwargs["retention_days"],
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("evaluation run insert unexpectedly returned no row")
            conn.execute(
                """
                INSERT INTO rag_evaluation_case_executions (
                    run_id, case_id, case_index
                )
                SELECT %s, selected.case_id, selected.ordinality - 1
                FROM jsonb_array_elements_text(%s::jsonb)
                     WITH ORDINALITY AS selected(case_id, ordinality)
                """,
                (row["id"], json.dumps(selected_case_ids)),
            )
        return run_from_row(row)

    def list_runs(self) -> list[EvaluationRunRecord]:
        return [
            run_from_row(row)
            for row in self._execute_all(
                "SELECT * FROM rag_evaluation_runs ORDER BY created_at DESC"
            )
        ]

    def get_run(self, run_id: str) -> EvaluationRunRecord | None:
        row = self._execute_optional(
            "SELECT * FROM rag_evaluation_runs WHERE id = %s", (run_id,)
        )
        return run_from_row(row) if row else None

    def update_run(
        self, run_id: str, changes: dict[str, Any]
    ) -> EvaluationRunRecord | None:
        unknown = set(changes) - _RUN_UPDATABLE_FIELDS
        if unknown:
            raise ValueError(
                f"unsupported evaluation run fields: {', '.join(sorted(unknown))}"
            )
        if not changes:
            return self.get_run(run_id)
        assignments: list[str] = []
        values: list[Any] = []
        for field, value in changes.items():
            assignments.append(
                f"{field} = %s::jsonb" if field in _RUN_JSON_FIELDS else f"{field} = %s"
            )
            values.append(
                json.dumps(value)
                if field in _RUN_JSON_FIELDS and value is not None
                else value
            )
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
            conn.execute(
                "DELETE FROM rag_evaluation_case_results WHERE run_id = %s", (run_id,)
            )

    def add_case_result(self, **kwargs: Any) -> EvaluationCaseResultRecord:
        payload = _result_payload_from_kwargs(kwargs)
        with self._connect() as conn:
            row = _upsert_case_result(
                conn,
                run_id=str(kwargs["run_id"]),
                case_id=str(kwargs["case_id"]),
                case_index=int(kwargs["case_index"]),
                result=payload,
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

    def list_case_executions(self, run_id: str) -> list[EvaluationCaseExecutionRecord]:
        return [
            case_execution_from_row(row)
            for row in self._execute_all(
                """
                SELECT * FROM rag_evaluation_case_executions
                WHERE run_id = %s
                ORDER BY case_index
                """,
                (run_id,),
            )
        ]

    def claim_next_case(
        self,
        run_id: str,
        *,
        run_token: str,
        stale_before: datetime | None = None,
    ) -> EvaluationCaseClaim:
        _validate_run_token(run_token)
        selected_stale_before = (
            stale_before or datetime.now(UTC) - DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT
        )
        with self._connect() as conn:
            run_row = conn.execute(
                "SELECT * FROM rag_evaluation_runs WHERE id = %s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return EvaluationCaseClaim("not_found", None, None)
            run = run_from_row(run_row)
            if run.status in _TERMINAL_RUN_STATUSES or run.cancellation_requested:
                return EvaluationCaseClaim("terminal", run, None)
            if run.status == "queued" and run.attempt_count >= run.max_attempts:
                run_row = conn.execute(
                    """
                    UPDATE rag_evaluation_runs
                    SET status = 'failed', stage = 'failed', progress_pct = 100,
                        error_code = 'evaluation_attempts_exhausted',
                        error_message_safe = 'Evaluation run exhausted its retry limit.',
                        completed_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (run_id,),
                ).fetchone()
                return EvaluationCaseClaim(
                    "terminal",
                    run_from_row(run_row),
                    None,  # type: ignore[arg-type]
                )

            owned_row = conn.execute(
                """
                SELECT * FROM rag_evaluation_case_executions
                WHERE run_id = %s AND status = 'running' AND run_token = %s
                ORDER BY case_index
                LIMIT 1
                FOR UPDATE
                """,
                (run_id, run_token),
            ).fetchone()
            if owned_row is not None:
                execution = case_execution_from_row(owned_row)
                disposition = (
                    "exhausted"
                    if execution.error_code == _EXHAUSTED_ERROR_CODE
                    else "claimed"
                )
                return EvaluationCaseClaim(disposition, run, execution)

            busy_row = conn.execute(
                """
                SELECT * FROM rag_evaluation_case_executions
                WHERE run_id = %s AND status = 'running'
                  AND last_heartbeat_at > %s
                ORDER BY last_heartbeat_at, case_index
                LIMIT 1
                FOR UPDATE
                """,
                (run_id, selected_stale_before),
            ).fetchone()
            if busy_row is not None:
                execution = case_execution_from_row(busy_row)
                return EvaluationCaseClaim(
                    "busy",
                    run,
                    execution,
                    retry_at=_lease_expires_at(execution.last_heartbeat_at),
                )

            candidate_row = conn.execute(
                """
                SELECT * FROM rag_evaluation_case_executions
                WHERE run_id = %s
                  AND (
                    status = 'queued'
                    OR (
                        status = 'running'
                        AND (last_heartbeat_at IS NULL OR last_heartbeat_at <= %s)
                    )
                  )
                ORDER BY
                    CASE WHEN attempt_count >= max_attempts THEN 0
                         WHEN status = 'running' THEN 1
                         ELSE 2 END,
                    case_index
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (run_id, selected_stale_before),
            ).fetchone()
            if candidate_row is None:
                busy_row = conn.execute(
                    """
                    SELECT * FROM rag_evaluation_case_executions
                    WHERE run_id = %s AND status = 'running'
                    ORDER BY last_heartbeat_at NULLS FIRST, case_index
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                if busy_row is not None:
                    execution = case_execution_from_row(busy_row)
                    return EvaluationCaseClaim(
                        "busy",
                        run,
                        execution,
                        retry_at=_lease_expires_at(execution.last_heartbeat_at),
                    )
                refreshed = _refresh_run_aggregate(conn, run_id)
                return EvaluationCaseClaim("terminal", refreshed, None)

            exhausted = int(candidate_row["attempt_count"]) >= int(
                candidate_row["max_attempts"]
            )
            if exhausted:
                claimed_row = conn.execute(
                    """
                    UPDATE rag_evaluation_case_executions
                    SET status = 'running', last_heartbeat_at = NOW(), run_token = %s,
                        error_code = %s, error_message_safe = %s,
                        completed_at = NULL, updated_at = NOW()
                    WHERE run_id = %s AND case_id = %s
                    RETURNING *
                    """,
                    (
                        run_token,
                        _EXHAUSTED_ERROR_CODE,
                        _EXHAUSTED_ERROR_MESSAGE,
                        run_id,
                        candidate_row["case_id"],
                    ),
                ).fetchone()
                disposition = "exhausted"
            else:
                claimed_row = conn.execute(
                    """
                    UPDATE rag_evaluation_case_executions
                    SET status = 'running', attempt_count = attempt_count + 1,
                        started_at = COALESCE(started_at, NOW()),
                        last_heartbeat_at = NOW(), run_token = %s,
                        error_code = NULL, error_message_safe = NULL,
                        completed_at = NULL, updated_at = NOW()
                    WHERE run_id = %s AND case_id = %s
                    RETURNING *
                    """,
                    (run_token, run_id, candidate_row["case_id"]),
                ).fetchone()
                disposition = "claimed"
            if claimed_row is None:
                raise RuntimeError("evaluation case claim unexpectedly returned no row")

            if run.status == "queued":
                run_row = conn.execute(
                    """
                    UPDATE rag_evaluation_runs
                    SET status = 'running', stage = 'running',
                        attempt_count = attempt_count + 1,
                        started_at = COALESCE(started_at, NOW()),
                        last_heartbeat_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (run_id,),
                ).fetchone()
            else:
                run_row = conn.execute(
                    """
                    UPDATE rag_evaluation_runs
                    SET last_heartbeat_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (run_id,),
                ).fetchone()
            if run_row is None:
                raise RuntimeError("evaluation run claim unexpectedly returned no row")
            return EvaluationCaseClaim(
                disposition,  # type: ignore[arg-type]
                run_from_row(run_row),
                case_execution_from_row(claimed_row),
            )

    def heartbeat_case(
        self,
        run_id: str,
        case_id: str,
        *,
        run_token: str,
    ) -> EvaluationCaseExecutionRecord | None:
        if not run_token:
            return None
        with self._connect() as conn:
            run_row = conn.execute(
                """
                SELECT id FROM rag_evaluation_runs
                WHERE id = %s AND status = 'running'
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            row = conn.execute(
                """
                UPDATE rag_evaluation_case_executions
                SET last_heartbeat_at = NOW(), updated_at = NOW()
                WHERE run_id = %s AND case_id = %s
                  AND status = 'running' AND run_token = %s
                RETURNING *
                """,
                (run_id, case_id, run_token),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE rag_evaluation_runs
                SET last_heartbeat_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status = 'running'
                """,
                (run_id,),
            )
        return case_execution_from_row(row)

    def requeue_case_attempt(
        self,
        run_id: str,
        case_id: str,
        *,
        run_token: str,
        error_code: str,
        error_message_safe: str,
    ) -> EvaluationCaseExecutionRecord | None:
        _validate_run_token(run_token)
        with self._connect() as conn:
            run_row = conn.execute(
                """
                SELECT id FROM rag_evaluation_runs
                WHERE id = %s AND status = 'running'
                  AND cancellation_requested = FALSE
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            row = conn.execute(
                """
                UPDATE rag_evaluation_case_executions
                SET status = 'queued', last_heartbeat_at = NULL, run_token = NULL,
                    error_code = %s, error_message_safe = %s, updated_at = NOW()
                WHERE run_id = %s AND case_id = %s
                  AND status = 'running' AND run_token = %s
                  AND attempt_count < max_attempts
                RETURNING *
                """,
                (
                    error_code,
                    error_message_safe,
                    run_id,
                    case_id,
                    run_token,
                ),
            ).fetchone()
        return case_execution_from_row(row) if row is not None else None

    def complete_case_attempt(
        self,
        run_id: str,
        case_id: str,
        *,
        run_token: str,
        result: EvaluationCaseResultPayload,
        execution_status: EvaluationCaseTerminalStatus = "complete",
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> EvaluationCaseCommit:
        _validate_run_token(run_token)
        if execution_status not in {"complete", "failed"}:
            raise ValueError("execution_status must be complete or failed")
        with self._connect() as conn:
            run_row = conn.execute(
                "SELECT * FROM rag_evaluation_runs WHERE id = %s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return EvaluationCaseCommit(False, None, None, None)
            execution_row = conn.execute(
                """
                SELECT * FROM rag_evaluation_case_executions
                WHERE run_id = %s AND case_id = %s
                FOR UPDATE
                """,
                (run_id, case_id),
            ).fetchone()
            current_result_row = conn.execute(
                """
                SELECT * FROM rag_evaluation_case_results
                WHERE run_id = %s AND case_id = %s
                """,
                (run_id, case_id),
            ).fetchone()
            run = run_from_row(run_row)
            if (
                execution_row is None
                or run.status != "running"
                or run.cancellation_requested
                or execution_row["status"] != "running"
                or execution_row.get("run_token") != run_token
            ):
                return EvaluationCaseCommit(
                    False,
                    run,
                    case_execution_from_row(execution_row)
                    if execution_row is not None
                    else None,
                    case_result_from_row(current_result_row)
                    if current_result_row is not None
                    else None,
                )

            result_row = _upsert_case_result(
                conn,
                run_id=run_id,
                case_id=case_id,
                case_index=int(execution_row["case_index"]),
                result=result,
            )
            selected_error_code = (
                error_code or execution_row.get("error_code")
                if execution_status == "failed"
                else None
            )
            selected_error_message = (
                error_message_safe
                or execution_row.get("error_message_safe")
                or result.error_message_safe
                if execution_status == "failed"
                else None
            )
            completed_execution_row = conn.execute(
                """
                UPDATE rag_evaluation_case_executions
                SET status = %s, run_token = NULL, last_heartbeat_at = NOW(),
                    error_code = %s, error_message_safe = %s,
                    completed_at = NOW(), updated_at = NOW()
                WHERE run_id = %s AND case_id = %s
                  AND status = 'running' AND run_token = %s
                RETURNING *
                """,
                (
                    execution_status,
                    selected_error_code,
                    selected_error_message,
                    run_id,
                    case_id,
                    run_token,
                ),
            ).fetchone()
            if completed_execution_row is None:
                raise RuntimeError(
                    "evaluation case lease changed during a locked completion"
                )
            refreshed_run = _refresh_run_aggregate(conn, run_id)
            return EvaluationCaseCommit(
                True,
                refreshed_run,
                case_execution_from_row(completed_execution_row),
                case_result_from_row(result_row),
            )

    def cancel_run(self, run_id: str) -> EvaluationRunRecord | None:
        with self._connect() as conn:
            run_row = conn.execute(
                "SELECT * FROM rag_evaluation_runs WHERE id = %s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            run = run_from_row(run_row)
            if run.status in _TERMINAL_RUN_STATUSES:
                return run
            conn.execute(
                """
                UPDATE rag_evaluation_case_executions
                SET status = 'cancelled', run_token = NULL,
                    completed_at = NOW(), updated_at = NOW()
                WHERE run_id = %s AND status IN ('queued', 'running')
                """,
                (run_id,),
            )
            updated_row = conn.execute(
                """
                UPDATE rag_evaluation_runs
                SET cancellation_requested = TRUE, status = 'cancelled',
                    stage = 'cancelled', progress_pct = 100,
                    completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (run_id,),
            ).fetchone()
        return run_from_row(updated_row) if updated_row is not None else None

    def reset_run_for_retry(
        self, run_id: str
    ) -> tuple[EvaluationRunRecord | None, bool]:
        with self._connect() as conn:
            run_row = conn.execute(
                "SELECT * FROM rag_evaluation_runs WHERE id = %s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None, False
            run = run_from_row(run_row)
            if (
                run.status not in {"failed", "partial", "cancelled"}
                or run.attempt_count >= run.max_attempts
            ):
                return run, False
            execution_count_row = conn.execute(
                """
                SELECT COUNT(*)::int AS count
                FROM rag_evaluation_case_executions
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
            if run.case_count > 0 and (
                execution_count_row is None or int(execution_count_row["count"]) == 0
            ):
                return run, False
            conn.execute(
                """
                WITH reset_cases AS (
                    UPDATE rag_evaluation_case_executions
                    SET status = 'queued', attempt_count = 0,
                        last_heartbeat_at = NULL, run_token = NULL,
                        error_code = NULL, error_message_safe = NULL,
                        started_at = NULL, completed_at = NULL, updated_at = NOW()
                    WHERE run_id = %s AND status <> 'complete'
                    RETURNING case_id
                )
                DELETE FROM rag_evaluation_case_results
                WHERE run_id = %s
                  AND case_id IN (SELECT case_id FROM reset_cases)
                """,
                (run_id, run_id),
            )
            counts = conn.execute(
                """
                SELECT COUNT(*)::int AS completed_count,
                       COUNT(*) FILTER (WHERE passed)::int AS passed_count,
                       COUNT(*) FILTER (WHERE NOT passed)::int AS failed_count
                FROM rag_evaluation_case_results
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
            completed_count = int(counts["completed_count"]) if counts else 0
            progress_pct = (
                int(completed_count / run.case_count * 100) if run.case_count else 0
            )
            updated_row = conn.execute(
                """
                UPDATE rag_evaluation_runs
                SET status = 'queued', stage = 'queued', progress_pct = %s,
                    completed_count = %s, passed_count = %s, failed_count = %s,
                    summary_json = '{}'::jsonb, cancellation_requested = FALSE,
                    error_code = NULL, error_message_safe = NULL,
                    completed_at = NULL, last_heartbeat_at = NULL, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (
                    progress_pct,
                    completed_count,
                    int(counts["passed_count"]) if counts else 0,
                    int(counts["failed_count"]) if counts else 0,
                    run_id,
                ),
            ).fetchone()
        return (
            run_from_row(updated_row) if updated_row is not None else None,
            updated_row is not None,
        )

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(EVALUATION_SCHEMA_SQL)


def dataset_from_row(row: dict[str, Any]) -> EvaluationDatasetRecord:
    return EvaluationDatasetRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]) if row.get("description") else None,
        source_format=str(row["source_format"]),
        cases=tuple(
            EvaluationCase.model_validate(item)
            for item in _json_list(row.get("cases_json"))
            if isinstance(item, dict)
        ),
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
        selected_case_ids=tuple(
            str(item) for item in _json_list(row.get("selected_case_ids"))
        ),
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
        primary_failure_stage=str(row["primary_failure_stage"])
        if row.get("primary_failure_stage")
        else None,
        failure_stages=tuple(
            str(item) for item in _json_list(row.get("failure_stages"))
        ),
        checks_json=_json_object(row.get("checks_json")),
        answer=str(row["answer"] or ""),
        sources_json=tuple(
            dict(item) for item in _json_object_list(row.get("sources_json"))
        ),
        diagnostic_json=_json_object(row.get("diagnostic_json")),
        trace_id=str(row["trace_id"]) if row.get("trace_id") else None,
        node_timings_json=tuple(
            dict(item) for item in _json_object_list(row.get("node_timings_json"))
        ),
        faithfulness_score=float(row["faithfulness_score"])
        if row.get("faithfulness_score") is not None
        else None,
        faithfulness_status=str(row["faithfulness_status"])
        if row.get("faithfulness_status")
        else None,
        unfounded_claims=tuple(
            str(item) for item in _json_list(row.get("unfounded_claims"))
        ),
        degraded=bool(row["degraded"]),
        degraded_reason=str(row["degraded_reason"])
        if row.get("degraded_reason")
        else None,
        latency_ms=int(row["latency_ms"]),
        error_message_safe=str(row["error_message_safe"])
        if row.get("error_message_safe")
        else None,
        created_at=row.get("created_at"),
    )


def case_execution_from_row(row: dict[str, Any]) -> EvaluationCaseExecutionRecord:
    return EvaluationCaseExecutionRecord(
        run_id=str(row["run_id"]),
        case_id=str(row["case_id"]),
        case_index=int(row["case_index"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        last_heartbeat_at=row.get("last_heartbeat_at"),
        run_token=str(row["run_token"]) if row.get("run_token") else None,
        error_code=str(row["error_code"]) if row.get("error_code") else None,
        error_message_safe=(
            str(row["error_message_safe"]) if row.get("error_message_safe") else None
        ),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )


def _validated_case_selection(kwargs: dict[str, Any]) -> tuple[str, ...]:
    selected_case_ids = tuple(str(item) for item in kwargs["selected_case_ids"])
    case_count = int(kwargs["case_count"])
    if len(selected_case_ids) != case_count:
        raise ValueError("case_count must match selected_case_ids")
    if len(set(selected_case_ids)) != len(selected_case_ids):
        raise ValueError("selected_case_ids must be unique")
    return selected_case_ids


def _validate_run_token(run_token: str) -> None:
    if not run_token.strip():
        raise ValueError("run_token must not be blank")


def _lease_expires_at(last_heartbeat_at: datetime | None) -> datetime:
    return (
        last_heartbeat_at + DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT
        if last_heartbeat_at is not None
        else datetime.now(UTC)
    )


def _result_payload_from_kwargs(kwargs: dict[str, Any]) -> EvaluationCaseResultPayload:
    return EvaluationCaseResultPayload(
        question=str(kwargs["question"]),
        status=str(kwargs["status"]),
        passed=bool(kwargs["passed"]),
        primary_failure_stage=(
            str(kwargs["primary_failure_stage"])
            if kwargs.get("primary_failure_stage")
            else None
        ),
        failure_stages=tuple(str(item) for item in kwargs.get("failure_stages", [])),
        checks_json=dict(kwargs.get("checks_json") or {}),
        answer=str(kwargs.get("answer") or ""),
        sources_json=tuple(dict(item) for item in kwargs.get("sources_json", [])),
        diagnostic_json=dict(kwargs.get("diagnostic_json") or {}),
        trace_id=str(kwargs["trace_id"]) if kwargs.get("trace_id") else None,
        node_timings_json=tuple(
            dict(item) for item in kwargs.get("node_timings_json", [])
        ),
        faithfulness_score=(
            float(kwargs["faithfulness_score"])
            if kwargs.get("faithfulness_score") is not None
            else None
        ),
        faithfulness_status=(
            str(kwargs["faithfulness_status"])
            if kwargs.get("faithfulness_status")
            else None
        ),
        unfounded_claims=tuple(
            str(item) for item in kwargs.get("unfounded_claims", [])
        ),
        degraded=bool(kwargs.get("degraded", False)),
        degraded_reason=(
            str(kwargs["degraded_reason"]) if kwargs.get("degraded_reason") else None
        ),
        latency_ms=int(kwargs.get("latency_ms") or 0),
        error_message_safe=(
            str(kwargs["error_message_safe"])
            if kwargs.get("error_message_safe")
            else None
        ),
    )


def _upsert_case_result(
    conn: Any,
    *,
    run_id: str,
    case_id: str,
    case_index: int,
    result: EvaluationCaseResultPayload,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO rag_evaluation_case_results (
            run_id, case_id, case_index, question, status, passed,
            primary_failure_stage, failure_stages, checks_json, answer,
            sources_json, diagnostic_json, trace_id, node_timings_json,
            faithfulness_score, faithfulness_status, unfounded_claims,
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
            run_id,
            case_id,
            case_index,
            result.question,
            result.status,
            result.passed,
            result.primary_failure_stage,
            json.dumps(result.failure_stages),
            json.dumps(result.checks_json),
            result.answer,
            json.dumps(result.sources_json),
            json.dumps(result.diagnostic_json),
            result.trace_id,
            json.dumps(result.node_timings_json),
            result.faithfulness_score,
            result.faithfulness_status,
            json.dumps(result.unfounded_claims),
            result.degraded,
            result.degraded_reason,
            result.latency_ms,
            result.error_message_safe,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("evaluation case result upsert unexpectedly returned no row")
    return row


def _refresh_run_aggregate(conn: Any, run_id: str) -> EvaluationRunRecord:
    run_row = conn.execute(
        "SELECT * FROM rag_evaluation_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    if run_row is None:
        raise RuntimeError("evaluation run disappeared during aggregation")
    execution_counts = conn.execute(
        """
        SELECT COUNT(*)::int AS case_count,
               COUNT(*) FILTER (
                   WHERE status IN ('complete', 'failed', 'cancelled')
               )::int AS terminal_count,
               COUNT(*) FILTER (WHERE status = 'complete')::int AS complete_count,
               COUNT(*) FILTER (
                   WHERE status IN ('failed', 'cancelled')
               )::int AS execution_failed_count
        FROM rag_evaluation_case_executions
        WHERE run_id = %s
        """,
        (run_id,),
    ).fetchone()
    result_rows = list(
        conn.execute(
            """
            SELECT * FROM rag_evaluation_case_results
            WHERE run_id = %s
            ORDER BY case_index
            """,
            (run_id,),
        ).fetchall()
    )
    run = run_from_row(run_row)
    case_count = int(execution_counts["case_count"]) if execution_counts else 0
    terminal_count = int(execution_counts["terminal_count"]) if execution_counts else 0
    complete_count = int(execution_counts["complete_count"]) if execution_counts else 0
    execution_failed_count = (
        int(execution_counts["execution_failed_count"]) if execution_counts else 0
    )
    completed_count = len(result_rows)
    passed_count = sum(1 for row in result_rows if bool(row["passed"]))
    failed_count = completed_count - passed_count
    missing_execution_state = case_count == 0 and run.case_count > 0
    is_terminal = missing_execution_state or (
        case_count > 0 and terminal_count >= case_count
    )
    progress_pct = (
        100
        if is_terminal
        else int(terminal_count / case_count * 100)
        if case_count
        else 0
    )
    if is_terminal:
        if missing_execution_state:
            status = "partial" if result_rows else "failed"
        elif execution_failed_count == 0:
            status = "complete"
        elif complete_count > 0:
            status = "partial"
        else:
            status = "failed"
        stage = status
        summary = summarize_results(
            [
                {
                    "passed": bool(row["passed"]),
                    "primary_failure_stage": row.get("primary_failure_stage"),
                    "checks": _json_object(row.get("checks_json")),
                    "latency_ms": int(row["latency_ms"]),
                }
                for row in result_rows
            ]
        )
        if missing_execution_state:
            error_code = "evaluation_case_execution_state_missing"
            error_message_safe = "Evaluation case execution state was not initialized."
        else:
            error_code = (
                "evaluation_case_execution_failed" if execution_failed_count else None
            )
            error_message_safe = (
                "One or more evaluation cases could not be executed."
                if execution_failed_count
                else None
            )
    else:
        status = "running"
        stage = f"case {terminal_count} of {case_count}"
        summary = run.summary_json
        error_code = run.error_code
        error_message_safe = run.error_message_safe
    updated_row = conn.execute(
        """
        UPDATE rag_evaluation_runs
        SET status = %s, stage = %s, progress_pct = %s,
            completed_count = %s, passed_count = %s, failed_count = %s,
            summary_json = %s::jsonb, error_code = %s,
            error_message_safe = %s, last_heartbeat_at = NOW(),
            completed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
            updated_at = NOW()
        WHERE id = %s
        RETURNING *
        """,
        (
            status,
            stage,
            progress_pct,
            completed_count,
            passed_count,
            failed_count,
            json.dumps(summary),
            error_code,
            error_message_safe,
            is_terminal,
            run_id,
        ),
    ).fetchone()
    if updated_row is None:
        raise RuntimeError("evaluation run aggregation unexpectedly returned no row")
    return run_from_row(updated_row)


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

CREATE TABLE IF NOT EXISTS rag_evaluation_case_executions (
    run_id UUID NOT NULL REFERENCES rag_evaluation_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    case_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_heartbeat_at TIMESTAMPTZ NULL,
    run_token TEXT NULL,
    error_code TEXT NULL,
    error_message_safe TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    PRIMARY KEY (run_id, case_id),
    CONSTRAINT rag_evaluation_case_executions_run_index_unique
        UNIQUE (run_id, case_index),
    CONSTRAINT rag_evaluation_case_executions_status_known CHECK (
        status IN ('queued', 'running', 'complete', 'failed', 'cancelled')
    ),
    CONSTRAINT rag_evaluation_case_executions_index_nonnegative CHECK (
        case_index >= 0
    ),
    CONSTRAINT rag_evaluation_case_executions_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
    )
);

INSERT INTO rag_evaluation_case_executions (
    run_id, case_id, case_index, status, attempt_count,
    started_at, completed_at, created_at, updated_at
)
SELECT
    run.id,
    selected.case_id,
    selected.ordinality - 1,
    CASE
        WHEN result.id IS NOT NULL THEN 'complete'
        WHEN run.status = 'cancelled' THEN 'cancelled'
        WHEN run.status IN ('complete', 'partial', 'failed') THEN 'failed'
        ELSE 'queued'
    END,
    CASE WHEN result.id IS NOT NULL THEN 1 ELSE 0 END,
    result.created_at,
    CASE
        WHEN result.id IS NOT NULL THEN result.created_at
        WHEN run.status IN ('complete', 'partial', 'failed', 'cancelled')
            THEN run.completed_at
        ELSE NULL
    END,
    run.created_at,
    run.updated_at
FROM rag_evaluation_runs AS run
CROSS JOIN LATERAL jsonb_array_elements_text(run.selected_case_ids)
    WITH ORDINALITY AS selected(case_id, ordinality)
LEFT JOIN rag_evaluation_case_results AS result
    ON result.run_id = run.id AND result.case_id = selected.case_id
WHERE run.status IN ('complete', 'partial', 'failed', 'cancelled')
ON CONFLICT (run_id, case_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS rag_evaluation_datasets_created_idx
    ON rag_evaluation_datasets (created_at DESC);
CREATE INDEX IF NOT EXISTS rag_evaluation_runs_created_idx
    ON rag_evaluation_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS rag_evaluation_runs_active_idx
    ON rag_evaluation_runs (status, updated_at)
    WHERE status NOT IN ('complete', 'partial', 'failed', 'cancelled');
CREATE UNIQUE INDEX IF NOT EXISTS rag_evaluation_case_results_run_case_uidx
    ON rag_evaluation_case_results (run_id, case_id);
CREATE INDEX IF NOT EXISTS rag_evaluation_case_executions_active_idx
    ON rag_evaluation_case_executions (
        run_id, status, last_heartbeat_at, case_index
    )
    WHERE status IN ('queued', 'running');
"""
