"""In-memory evaluation repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4

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
    _RUN_UPDATABLE_FIELDS,
)
from ..scoring import summarize_results


_TERMINAL_RUN_STATUSES = frozenset({"complete", "partial", "failed", "cancelled"})
_EXHAUSTED_ERROR_CODE = "evaluation_case_attempts_exhausted"
_EXHAUSTED_ERROR_MESSAGE = "Evaluation case exhausted its retry limit."


class InMemoryEvaluationRepository:
    def __init__(self) -> None:
        self._datasets: dict[str, EvaluationDatasetRecord] = {}
        self._runs: dict[str, EvaluationRunRecord] = {}
        self._results: dict[str, list[EvaluationCaseResultRecord]] = {}
        self._case_executions: dict[str, dict[str, EvaluationCaseExecutionRecord]] = {}
        self._lock = RLock()

    def create_dataset(self, **kwargs: Any) -> EvaluationDatasetRecord:
        now = datetime.now(UTC)
        record = EvaluationDatasetRecord(
            id=str(uuid4()),
            name=str(kwargs["name"]),
            description=kwargs.get("description"),
            source_format=str(kwargs["source_format"]),
            cases=tuple(kwargs["cases"]),
            metadata=dict(kwargs.get("metadata") or {}),
            created_by=str(kwargs["created_by"]) if kwargs.get("created_by") else None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._datasets[record.id] = record
        return record

    def list_datasets(self) -> list[EvaluationDatasetRecord]:
        return sorted(
            self._datasets.values(),
            key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def get_dataset(self, dataset_id: str) -> EvaluationDatasetRecord | None:
        return self._datasets.get(dataset_id)

    def create_run(self, **kwargs: Any) -> EvaluationRunRecord:
        selected_case_ids = _validated_case_selection(kwargs)
        now = datetime.now(UTC)
        record = EvaluationRunRecord(
            id=str(uuid4()),
            dataset_id=str(kwargs["dataset_id"]),
            user_id=str(kwargs["user_id"]),
            permission_version=int(kwargs["permission_version"]),
            user_email=str(kwargs["user_email"]),
            account_type=str(kwargs["account_type"]),
            group_paths=tuple(str(item) for item in kwargs["group_paths"]),
            clearance_level=normalize_clearance_level(kwargs.get("clearance_level")),
            group_path=str(kwargs["group_path"]) if kwargs.get("group_path") else None,
            document_ids=tuple(str(item) for item in kwargs["document_ids"]),
            selected_case_ids=selected_case_ids,
            rag_config_snapshot=dict(kwargs["rag_config_snapshot"]),
            status="queued",
            stage="queued",
            progress_pct=0,
            case_count=int(kwargs["case_count"]),
            completed_count=0,
            passed_count=0,
            failed_count=0,
            summary_json={},
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
            expires_at=now + timedelta(days=int(kwargs["retention_days"])),
        )
        with self._lock:
            self._runs[record.id] = record
            self._results[record.id] = []
            self._case_executions[record.id] = {
                case_id: EvaluationCaseExecutionRecord(
                    run_id=record.id,
                    case_id=case_id,
                    case_index=index,
                    status="queued",
                    attempt_count=0,
                    max_attempts=3,
                    last_heartbeat_at=None,
                    run_token=None,
                    error_code=None,
                    error_message_safe=None,
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                )
                for index, case_id in enumerate(selected_case_ids)
            }
        return record

    def list_runs(self) -> list[EvaluationRunRecord]:
        return sorted(
            self._runs.values(),
            key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def get_run(self, run_id: str) -> EvaluationRunRecord | None:
        return self._runs.get(run_id)

    def update_run(
        self, run_id: str, changes: dict[str, Any]
    ) -> EvaluationRunRecord | None:
        unknown = set(changes) - _RUN_UPDATABLE_FIELDS
        if unknown:
            raise ValueError(
                f"unsupported evaluation run fields: {', '.join(sorted(unknown))}"
            )
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            updated = replace(run, **changes, updated_at=datetime.now(UTC))
            self._runs[run_id] = updated
            return updated

    def start_attempt(self, run_id: str) -> tuple[EvaluationRunRecord | None, bool]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None, False
            if run.status != "queued" or run.attempt_count >= run.max_attempts:
                return run, False
            now = datetime.now(UTC)
            updated = replace(
                run,
                status="running",
                stage="running",
                progress_pct=0,
                attempt_count=run.attempt_count + 1,
                started_at=run.started_at or now,
                last_heartbeat_at=now,
                updated_at=now,
            )
            self._runs[run_id] = updated
            return updated, True

    def heartbeat(self, run_id: str) -> EvaluationRunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            updated = replace(
                run, last_heartbeat_at=datetime.now(UTC), updated_at=datetime.now(UTC)
            )
            self._runs[run_id] = updated
            return updated

    def clear_case_results(self, run_id: str) -> None:
        with self._lock:
            self._results[run_id] = []

    def add_case_result(self, **kwargs: Any) -> EvaluationCaseResultRecord:
        payload = _result_payload_from_kwargs(kwargs)
        with self._lock:
            existing = _find_case_result(
                self._results.get(str(kwargs["run_id"]), []),
                str(kwargs["case_id"]),
            )
            record = _case_result_record(
                run_id=str(kwargs["run_id"]),
                case_id=str(kwargs["case_id"]),
                case_index=int(kwargs["case_index"]),
                payload=payload,
                existing=existing,
            )
            rows = [
                item
                for item in self._results.get(record.run_id, [])
                if item.case_id != record.case_id
            ]
            rows.append(record)
            self._results[record.run_id] = rows
        return record

    def list_case_results(self, run_id: str) -> list[EvaluationCaseResultRecord]:
        return sorted(self._results.get(run_id, []), key=lambda item: item.case_index)

    def list_case_executions(self, run_id: str) -> list[EvaluationCaseExecutionRecord]:
        return sorted(
            self._case_executions.get(run_id, {}).values(),
            key=lambda item: item.case_index,
        )

    def claim_next_case(
        self,
        run_id: str,
        *,
        run_token: str,
        stale_before: datetime | None = None,
    ) -> EvaluationCaseClaim:
        _validate_run_token(run_token)
        now = datetime.now(UTC)
        selected_stale_before = (
            stale_before or now - DEFAULT_EVALUATION_CASE_LEASE_TIMEOUT
        )
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return EvaluationCaseClaim("not_found", None, None)
            if run.status in _TERMINAL_RUN_STATUSES or run.cancellation_requested:
                return EvaluationCaseClaim("terminal", run, None)
            if run.status == "queued" and run.attempt_count >= run.max_attempts:
                failed = replace(
                    run,
                    status="failed",
                    stage="failed",
                    progress_pct=100,
                    error_code="evaluation_attempts_exhausted",
                    error_message_safe="Evaluation run exhausted its retry limit.",
                    completed_at=now,
                    updated_at=now,
                )
                self._runs[run_id] = failed
                return EvaluationCaseClaim("terminal", failed, None)

            executions = self._case_executions.get(run_id, {})
            owned = next(
                (
                    item
                    for item in executions.values()
                    if item.status == "running" and item.run_token == run_token
                ),
                None,
            )
            if owned is not None:
                disposition = (
                    "exhausted"
                    if owned.error_code == _EXHAUSTED_ERROR_CODE
                    else "claimed"
                )
                return EvaluationCaseClaim(disposition, run, owned)

            fresh = min(
                (
                    item
                    for item in executions.values()
                    if item.status == "running"
                    and item.last_heartbeat_at is not None
                    and item.last_heartbeat_at > selected_stale_before
                ),
                key=lambda item: (item.last_heartbeat_at, item.case_index),
                default=None,
            )
            if fresh is not None:
                return EvaluationCaseClaim(
                    "busy",
                    run,
                    fresh,
                    retry_at=_lease_expires_at(fresh.last_heartbeat_at),
                )

            candidates = [
                item
                for item in executions.values()
                if item.status == "queued"
                or (
                    item.status == "running"
                    and (
                        item.last_heartbeat_at is None
                        or item.last_heartbeat_at <= selected_stale_before
                    )
                )
            ]
            if not candidates:
                refreshed = _refresh_run_aggregate(
                    run,
                    tuple(executions.values()),
                    tuple(self._results.get(run_id, [])),
                    now=now,
                )
                self._runs[run_id] = refreshed
                return EvaluationCaseClaim("terminal", refreshed, None)
            selected = min(
                candidates,
                key=lambda item: (
                    0
                    if item.attempt_count >= item.max_attempts
                    else 1
                    if item.status == "running"
                    else 2,
                    item.case_index,
                ),
            )
            exhausted = selected.attempt_count >= selected.max_attempts
            claimed = replace(
                selected,
                status="running",
                attempt_count=(
                    selected.attempt_count if exhausted else selected.attempt_count + 1
                ),
                last_heartbeat_at=now,
                run_token=run_token,
                error_code=_EXHAUSTED_ERROR_CODE if exhausted else None,
                error_message_safe=_EXHAUSTED_ERROR_MESSAGE if exhausted else None,
                started_at=selected.started_at or now,
                completed_at=None,
                updated_at=now,
            )
            executions[selected.case_id] = claimed
            if run.status == "queued":
                run = replace(
                    run,
                    status="running",
                    stage="running",
                    attempt_count=run.attempt_count + 1,
                    started_at=run.started_at or now,
                    last_heartbeat_at=now,
                    updated_at=now,
                )
            else:
                run = replace(run, last_heartbeat_at=now, updated_at=now)
            self._runs[run_id] = run
            return EvaluationCaseClaim(
                "exhausted" if exhausted else "claimed",
                run,
                claimed,
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
        with self._lock:
            run = self._runs.get(run_id)
            execution = self._case_executions.get(run_id, {}).get(case_id)
            if (
                run is None
                or run.status != "running"
                or execution is None
                or execution.status != "running"
                or execution.run_token != run_token
            ):
                return None
            now = datetime.now(UTC)
            updated = replace(execution, last_heartbeat_at=now, updated_at=now)
            self._case_executions[run_id][case_id] = updated
            self._runs[run_id] = replace(run, last_heartbeat_at=now, updated_at=now)
            return updated

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
        with self._lock:
            run = self._runs.get(run_id)
            execution = self._case_executions.get(run_id, {}).get(case_id)
            if (
                run is None
                or run.status != "running"
                or run.cancellation_requested
                or execution is None
                or execution.status != "running"
                or execution.run_token != run_token
                or execution.attempt_count >= execution.max_attempts
            ):
                return None
            updated = replace(
                execution,
                status="queued",
                last_heartbeat_at=None,
                run_token=None,
                error_code=error_code,
                error_message_safe=error_message_safe,
                updated_at=datetime.now(UTC),
            )
            self._case_executions[run_id][case_id] = updated
            return updated

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
        with self._lock:
            run = self._runs.get(run_id)
            execution = self._case_executions.get(run_id, {}).get(case_id)
            existing_result = _find_case_result(self._results.get(run_id, []), case_id)
            if (
                run is None
                or execution is None
                or run.status != "running"
                or run.cancellation_requested
                or execution.status != "running"
                or execution.run_token != run_token
            ):
                return EvaluationCaseCommit(False, run, execution, existing_result)
            now = datetime.now(UTC)
            result_record = _case_result_record(
                run_id=run_id,
                case_id=case_id,
                case_index=execution.case_index,
                payload=result,
                existing=existing_result,
                now=now,
            )
            self._results[run_id] = [
                item
                for item in self._results.get(run_id, [])
                if item.case_id != case_id
            ] + [result_record]
            selected_error_code = None
            selected_error_message = None
            if execution_status == "failed":
                selected_error_code = error_code or execution.error_code
                selected_error_message = (
                    error_message_safe
                    or execution.error_message_safe
                    or result.error_message_safe
                )
            completed_execution = replace(
                execution,
                status=execution_status,
                run_token=None,
                last_heartbeat_at=now,
                error_code=selected_error_code,
                error_message_safe=selected_error_message,
                completed_at=now,
                updated_at=now,
            )
            self._case_executions[run_id][case_id] = completed_execution
            refreshed = _refresh_run_aggregate(
                run,
                tuple(self._case_executions[run_id].values()),
                tuple(self._results[run_id]),
                now=now,
            )
            self._runs[run_id] = refreshed
            return EvaluationCaseCommit(
                True, refreshed, completed_execution, result_record
            )

    def cancel_run(self, run_id: str) -> EvaluationRunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.status in _TERMINAL_RUN_STATUSES:
                return run
            now = datetime.now(UTC)
            self._case_executions[run_id] = {
                case_id: replace(
                    execution,
                    status="cancelled",
                    run_token=None,
                    completed_at=now,
                    updated_at=now,
                )
                if execution.status in {"queued", "running"}
                else execution
                for case_id, execution in self._case_executions.get(run_id, {}).items()
            }
            cancelled = replace(
                run,
                cancellation_requested=True,
                status="cancelled",
                stage="cancelled",
                progress_pct=100,
                completed_at=now,
                updated_at=now,
            )
            self._runs[run_id] = cancelled
            return cancelled

    def reset_run_for_retry(
        self, run_id: str
    ) -> tuple[EvaluationRunRecord | None, bool]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None, False
            if (
                run.status not in {"failed", "partial", "cancelled"}
                or run.attempt_count >= run.max_attempts
            ):
                return run, False
            now = datetime.now(UTC)
            executions = self._case_executions.get(run_id, {})
            if run.case_count > 0 and not executions:
                return run, False
            reset_case_ids = {
                case_id
                for case_id, execution in executions.items()
                if execution.status != "complete"
            }
            self._case_executions[run_id] = {
                case_id: replace(
                    execution,
                    status="queued",
                    attempt_count=0,
                    last_heartbeat_at=None,
                    run_token=None,
                    error_code=None,
                    error_message_safe=None,
                    started_at=None,
                    completed_at=None,
                    updated_at=now,
                )
                if case_id in reset_case_ids
                else execution
                for case_id, execution in executions.items()
            }
            retained_results = [
                item
                for item in self._results.get(run_id, [])
                if item.case_id not in reset_case_ids
            ]
            self._results[run_id] = retained_results
            completed_count = len(retained_results)
            passed_count = sum(1 for item in retained_results if item.passed)
            retried = replace(
                run,
                status="queued",
                stage="queued",
                progress_pct=(
                    int(completed_count / run.case_count * 100) if run.case_count else 0
                ),
                completed_count=completed_count,
                passed_count=passed_count,
                failed_count=completed_count - passed_count,
                summary_json={},
                cancellation_requested=False,
                error_code=None,
                error_message_safe=None,
                completed_at=None,
                last_heartbeat_at=None,
                updated_at=now,
            )
            self._runs[run_id] = retried
            return retried, True


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


def _case_result_record(
    *,
    run_id: str,
    case_id: str,
    case_index: int,
    payload: EvaluationCaseResultPayload,
    existing: EvaluationCaseResultRecord | None,
    now: datetime | None = None,
) -> EvaluationCaseResultRecord:
    created_at = now or datetime.now(UTC)
    return EvaluationCaseResultRecord(
        id=existing.id if existing is not None else str(uuid4()),
        run_id=run_id,
        case_id=case_id,
        case_index=case_index,
        question=payload.question,
        status=payload.status,
        passed=payload.passed,
        primary_failure_stage=payload.primary_failure_stage,
        failure_stages=payload.failure_stages,
        checks_json=dict(payload.checks_json),
        answer=payload.answer,
        sources_json=tuple(dict(item) for item in payload.sources_json),
        diagnostic_json=dict(payload.diagnostic_json),
        trace_id=payload.trace_id,
        node_timings_json=tuple(dict(item) for item in payload.node_timings_json),
        faithfulness_score=payload.faithfulness_score,
        faithfulness_status=payload.faithfulness_status,
        unfounded_claims=payload.unfounded_claims,
        degraded=payload.degraded,
        degraded_reason=payload.degraded_reason,
        latency_ms=payload.latency_ms,
        error_message_safe=payload.error_message_safe,
        created_at=existing.created_at if existing is not None else created_at,
    )


def _find_case_result(
    results: list[EvaluationCaseResultRecord], case_id: str
) -> EvaluationCaseResultRecord | None:
    return next((item for item in results if item.case_id == case_id), None)


def _refresh_run_aggregate(
    run: EvaluationRunRecord,
    executions: tuple[EvaluationCaseExecutionRecord, ...],
    results: tuple[EvaluationCaseResultRecord, ...],
    *,
    now: datetime,
) -> EvaluationRunRecord:
    case_count = len(executions)
    terminal_count = sum(
        1 for item in executions if item.status in {"complete", "failed", "cancelled"}
    )
    complete_count = sum(1 for item in executions if item.status == "complete")
    execution_failed_count = sum(
        1 for item in executions if item.status in {"failed", "cancelled"}
    )
    ordered_results = sorted(results, key=lambda item: item.case_index)
    completed_count = len(ordered_results)
    passed_count = sum(1 for item in ordered_results if item.passed)
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
    if not is_terminal:
        return replace(
            run,
            status="running",
            stage=f"case {terminal_count} of {case_count}",
            progress_pct=progress_pct,
            completed_count=completed_count,
            passed_count=passed_count,
            failed_count=failed_count,
            last_heartbeat_at=now,
            completed_at=None,
            updated_at=now,
        )
    if missing_execution_state:
        status = "partial" if ordered_results else "failed"
        error_code = "evaluation_case_execution_state_missing"
        error_message_safe = "Evaluation case execution state was not initialized."
    else:
        status = (
            "complete"
            if execution_failed_count == 0
            else "partial"
            if complete_count > 0
            else "failed"
        )
        error_code = (
            "evaluation_case_execution_failed" if execution_failed_count else None
        )
        error_message_safe = (
            "One or more evaluation cases could not be executed."
            if execution_failed_count
            else None
        )
    summary = summarize_results(
        [
            {
                "passed": item.passed,
                "primary_failure_stage": item.primary_failure_stage,
                "checks": item.checks_json,
                "latency_ms": item.latency_ms,
            }
            for item in ordered_results
        ]
    )
    return replace(
        run,
        status=status,  # type: ignore[arg-type]
        stage=status,
        progress_pct=100,
        completed_count=completed_count,
        passed_count=passed_count,
        failed_count=failed_count,
        summary_json=summary,
        error_code=error_code,
        error_message_safe=error_message_safe,
        last_heartbeat_at=now,
        completed_at=now,
        updated_at=now,
    )
