"""In-memory evaluation repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4

from ..shared.contracts.clearance import normalize_clearance_level
from .evaluation_models import (
    EvaluationCaseResultRecord,
    EvaluationDatasetRecord,
    EvaluationRunRecord,
    _RUN_UPDATABLE_FIELDS,
)


class InMemoryEvaluationRepository:
    def __init__(self) -> None:
        self._datasets: dict[str, EvaluationDatasetRecord] = {}
        self._runs: dict[str, EvaluationRunRecord] = {}
        self._results: dict[str, list[EvaluationCaseResultRecord]] = {}
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
        return sorted(self._datasets.values(), key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def get_dataset(self, dataset_id: str) -> EvaluationDatasetRecord | None:
        return self._datasets.get(dataset_id)

    def create_run(self, **kwargs: Any) -> EvaluationRunRecord:
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
            selected_case_ids=tuple(str(item) for item in kwargs["selected_case_ids"]),
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
        return record

    def list_runs(self) -> list[EvaluationRunRecord]:
        return sorted(self._runs.values(), key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    def get_run(self, run_id: str) -> EvaluationRunRecord | None:
        return self._runs.get(run_id)

    def update_run(self, run_id: str, changes: dict[str, Any]) -> EvaluationRunRecord | None:
        unknown = set(changes) - _RUN_UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"unsupported evaluation run fields: {', '.join(sorted(unknown))}")
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
            updated = replace(run, last_heartbeat_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            self._runs[run_id] = updated
            return updated

    def clear_case_results(self, run_id: str) -> None:
        with self._lock:
            self._results[run_id] = []

    def add_case_result(self, **kwargs: Any) -> EvaluationCaseResultRecord:
        now = datetime.now(UTC)
        record = EvaluationCaseResultRecord(
            id=str(uuid4()),
            run_id=str(kwargs["run_id"]),
            case_id=str(kwargs["case_id"]),
            case_index=int(kwargs["case_index"]),
            question=str(kwargs["question"]),
            status=str(kwargs["status"]),
            passed=bool(kwargs["passed"]),
            primary_failure_stage=str(kwargs["primary_failure_stage"]) if kwargs.get("primary_failure_stage") else None,
            failure_stages=tuple(str(item) for item in kwargs.get("failure_stages", [])),
            checks_json=dict(kwargs.get("checks_json") or {}),
            answer=str(kwargs.get("answer") or ""),
            sources_json=tuple(dict(item) for item in kwargs.get("sources_json", [])),
            diagnostic_json=dict(kwargs.get("diagnostic_json") or {}),
            trace_id=str(kwargs["trace_id"]) if kwargs.get("trace_id") else None,
            node_timings_json=tuple(dict(item) for item in kwargs.get("node_timings_json", [])),
            faithfulness_score=float(kwargs["faithfulness_score"]) if kwargs.get("faithfulness_score") is not None else None,
            faithfulness_status=str(kwargs["faithfulness_status"]) if kwargs.get("faithfulness_status") else None,
            unfounded_claims=tuple(str(item) for item in kwargs.get("unfounded_claims", [])),
            degraded=bool(kwargs.get("degraded", False)),
            degraded_reason=str(kwargs["degraded_reason"]) if kwargs.get("degraded_reason") else None,
            latency_ms=int(kwargs.get("latency_ms") or 0),
            error_message_safe=str(kwargs["error_message_safe"]) if kwargs.get("error_message_safe") else None,
            created_at=now,
        )
        with self._lock:
            rows = [item for item in self._results.get(record.run_id, []) if item.case_id != record.case_id]
            rows.append(record)
            self._results[record.run_id] = rows
        return record

    def list_case_results(self, run_id: str) -> list[EvaluationCaseResultRecord]:
        return sorted(self._results.get(run_id, []), key=lambda item: item.case_index)
