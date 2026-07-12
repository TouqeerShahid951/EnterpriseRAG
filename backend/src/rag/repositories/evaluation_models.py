"""Evaluation repository contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from ..schemas.evaluations import EvaluationCase, EvaluationRunStatus


@dataclass(frozen=True)
class EvaluationDatasetRecord:
    id: str
    name: str
    description: str | None
    source_format: str
    cases: tuple[EvaluationCase, ...]
    metadata: dict[str, Any]
    created_by: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class EvaluationRunRecord:
    id: str
    dataset_id: str
    user_id: str
    permission_version: int
    user_email: str
    account_type: str
    group_paths: tuple[str, ...]
    clearance_level: str
    group_path: str | None
    document_ids: tuple[str, ...]
    selected_case_ids: tuple[str, ...]
    rag_config_snapshot: dict[str, Any]
    status: EvaluationRunStatus
    stage: str
    progress_pct: int
    case_count: int
    completed_count: int
    passed_count: int
    failed_count: int
    summary_json: dict[str, Any]
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
    expires_at: datetime | None


@dataclass(frozen=True)
class EvaluationCaseResultRecord:
    id: str
    run_id: str
    case_id: str
    case_index: int
    question: str
    status: str
    passed: bool
    primary_failure_stage: str | None
    failure_stages: tuple[str, ...]
    checks_json: dict[str, Any]
    answer: str
    sources_json: tuple[dict[str, Any], ...]
    diagnostic_json: dict[str, Any]
    trace_id: str | None
    node_timings_json: tuple[dict[str, Any], ...]
    faithfulness_score: float | None
    faithfulness_status: str | None
    unfounded_claims: tuple[str, ...]
    degraded: bool
    degraded_reason: str | None
    latency_ms: int
    error_message_safe: str | None
    created_at: datetime | None


class EvaluationRepository(Protocol):
    def create_dataset(
        self,
        *,
        name: str,
        description: str | None,
        source_format: str,
        cases: list[EvaluationCase],
        metadata: dict[str, Any],
        created_by: str | None,
    ) -> EvaluationDatasetRecord: ...
    def list_datasets(self) -> list[EvaluationDatasetRecord]: ...
    def get_dataset(self, dataset_id: str) -> EvaluationDatasetRecord | None: ...
    def create_run(
        self,
        *,
        dataset_id: str,
        user_id: str,
        permission_version: int,
        user_email: str,
        account_type: str,
        group_paths: list[str],
        group_path: str | None,
        document_ids: list[str],
        selected_case_ids: list[str],
        rag_config_snapshot: dict[str, Any],
        case_count: int,
        retention_days: int,
    ) -> EvaluationRunRecord: ...
    def list_runs(self) -> list[EvaluationRunRecord]: ...
    def get_run(self, run_id: str) -> EvaluationRunRecord | None: ...
    def update_run(self, run_id: str, changes: dict[str, Any]) -> EvaluationRunRecord | None: ...
    def start_attempt(self, run_id: str) -> tuple[EvaluationRunRecord | None, bool]: ...
    def heartbeat(self, run_id: str) -> EvaluationRunRecord | None: ...
    def clear_case_results(self, run_id: str) -> None: ...
    def add_case_result(self, **kwargs: Any) -> EvaluationCaseResultRecord: ...
    def list_case_results(self, run_id: str) -> list[EvaluationCaseResultRecord]: ...


_RUN_UPDATABLE_FIELDS = {
    "status",
    "stage",
    "progress_pct",
    "completed_count",
    "passed_count",
    "failed_count",
    "summary_json",
    "error_code",
    "error_message_safe",
    "cancellation_requested",
    "started_at",
    "completed_at",
}
_RUN_JSON_FIELDS = {"summary_json", "rag_config_snapshot", "group_paths", "document_ids", "selected_case_ids"}
