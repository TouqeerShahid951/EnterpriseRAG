"""Application service for RAG evaluation datasets and runs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..auth.context import UserContext
from ..repositories.evaluations import (
    EvaluationCaseResultRecord,
    EvaluationDatasetRecord,
    EvaluationRepository,
    EvaluationRunRecord,
)
from ..repositories.rag_config import effective_rag_config
from ..query.rag_config_mapping import rag_config_response
from ..schemas.evaluations import (
    EvaluationCaseResult,
    EvaluationDatasetDetail,
    EvaluationDatasetSummary,
    EvaluationRunDetail,
    EvaluationRunSummary,
)
from .datasets import EvaluationDatasetError, normalize_dataset_content
from .queue import EvaluationRunQueue


class EvaluationActionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EvaluationService:
    def __init__(
        self,
        *,
        repo_factory: Callable[[], EvaluationRepository],
        queue_factory: Callable[[], EvaluationRunQueue],
        retention_days: int,
        rag_config_snapshot_factory: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.repo_factory = repo_factory
        self.queue_factory = queue_factory
        self.retention_days = retention_days
        self.rag_config_snapshot_factory = rag_config_snapshot_factory or _rag_config_snapshot

    def import_dataset(
        self,
        *,
        content: str,
        source_format: str,
        name: str | None,
        user_id: str | None,
    ) -> EvaluationDatasetDetail:
        try:
            normalized = normalize_dataset_content(content, name=name, source_format=source_format)
        except EvaluationDatasetError as exc:
            raise EvaluationActionError(exc.code, exc.message) from exc
        record = self.repo_factory().create_dataset(
            name=normalized.name,
            description=normalized.description,
            source_format=normalized.source_format,
            cases=list(normalized.cases),
            metadata=normalized.metadata,
            created_by=user_id,
        )
        return dataset_detail(record)

    def list_datasets(self) -> list[EvaluationDatasetSummary]:
        return [dataset_summary(record) for record in self.repo_factory().list_datasets()]

    def get_dataset(self, dataset_id: str) -> EvaluationDatasetDetail:
        record = self.repo_factory().get_dataset(dataset_id)
        if record is None:
            raise EvaluationActionError("evaluation_dataset_not_found", "Evaluation dataset was not found.")
        return dataset_detail(record)

    def submit_run(
        self,
        *,
        dataset_id: str,
        user: UserContext,
        group_path: str | None,
        document_ids: list[str],
        case_ids: list[str],
        limit: int | None,
    ) -> EvaluationRunSummary:
        repo = self.repo_factory()
        dataset = repo.get_dataset(dataset_id)
        if dataset is None:
            raise EvaluationActionError("evaluation_dataset_not_found", "Evaluation dataset was not found.")
        selected = _select_cases(dataset, case_ids=case_ids, limit=limit)
        if not selected:
            raise EvaluationActionError("evaluation_run_empty", "No evaluation cases matched the run selection.")
        run = repo.create_run(
            dataset_id=dataset.id,
            user_id=user.user_id,
            permission_version=user.permission_version,
            user_email=user.email,
            account_type=user.account_type,
            group_paths=list(user.group_paths),
            clearance_level=user.clearance_level,
            group_path=group_path,
            document_ids=document_ids,
            selected_case_ids=[case.id for case in selected],
            rag_config_snapshot=self.rag_config_snapshot_factory(),
            case_count=len(selected),
            retention_days=self.retention_days,
        )
        try:
            self.queue_factory().enqueue(run.id)
        except RuntimeError as exc:
            run = repo.update_run(run.id, {
                "status": "failed",
                "stage": "failed",
                "progress_pct": 100,
                "error_code": "evaluation_enqueue_failed",
                "error_message_safe": str(exc)[:300],
                "completed_at": datetime.now(UTC),
            }) or run
            raise EvaluationActionError("evaluation_enqueue_failed", "Evaluation run could not be queued.") from exc
        return run_summary(run, dataset)

    def list_runs(self) -> list[EvaluationRunSummary]:
        repo = self.repo_factory()
        runs = repo.list_runs()
        datasets = {dataset.id: dataset for dataset in repo.list_datasets()}
        return [run_summary(run, datasets.get(run.dataset_id)) for run in runs]

    def get_run(self, run_id: str) -> EvaluationRunDetail:
        repo = self.repo_factory()
        run = repo.get_run(run_id)
        if run is None:
            raise EvaluationActionError("evaluation_run_not_found", "Evaluation run was not found.")
        dataset = repo.get_dataset(run.dataset_id)
        results = repo.list_case_results(run.id)
        return run_detail(run, dataset, results)

    def cancel(self, run_id: str) -> EvaluationRunSummary:
        repo = self.repo_factory()
        run = repo.get_run(run_id)
        if run is None:
            raise EvaluationActionError("evaluation_run_not_found", "Evaluation run was not found.")
        if run.status in {"complete", "partial", "failed", "cancelled"}:
            return run_summary(run, repo.get_dataset(run.dataset_id))
        updated = repo.update_run(run.id, {
            "cancellation_requested": True,
            "status": "cancelled",
            "stage": "cancelled",
            "progress_pct": 100,
            "completed_at": datetime.now(UTC),
        }) or run
        return run_summary(updated, repo.get_dataset(updated.dataset_id))

    def retry(self, run_id: str) -> EvaluationRunSummary:
        repo = self.repo_factory()
        run = repo.get_run(run_id)
        if run is None:
            raise EvaluationActionError("evaluation_run_not_found", "Evaluation run was not found.")
        if run.status not in {"failed", "partial", "cancelled"}:
            raise EvaluationActionError("evaluation_run_not_retryable", "Only failed, partial, or cancelled runs can be retried.")
        if run.attempt_count >= run.max_attempts:
            raise EvaluationActionError("evaluation_retry_exhausted", "This evaluation run has reached its retry limit.")
        repo.clear_case_results(run.id)
        updated = repo.update_run(run.id, {
            "status": "queued",
            "stage": "queued",
            "progress_pct": 0,
            "completed_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "summary_json": {},
            "cancellation_requested": False,
            "error_code": None,
            "error_message_safe": None,
            "completed_at": None,
        }) or run
        try:
            self.queue_factory().enqueue(updated.id)
        except RuntimeError as exc:
            repo.update_run(updated.id, {
                "status": "failed",
                "stage": "failed",
                "progress_pct": 100,
                "error_code": "evaluation_enqueue_failed",
                "error_message_safe": str(exc)[:300],
                "completed_at": datetime.now(UTC),
            })
            raise EvaluationActionError("evaluation_enqueue_failed", "Evaluation run could not be queued.") from exc
        return run_summary(updated, repo.get_dataset(updated.dataset_id))


def dataset_summary(record: EvaluationDatasetRecord) -> EvaluationDatasetSummary:
    return EvaluationDatasetSummary(
        id=record.id,
        name=record.name,
        description=record.description,
        source_format=record.source_format,
        case_count=len(record.cases),
        created_by=record.created_by,
        created_at=_iso(record.created_at),
        updated_at=_iso(record.updated_at),
    )


def dataset_detail(record: EvaluationDatasetRecord) -> EvaluationDatasetDetail:
    return EvaluationDatasetDetail(
        **dataset_summary(record).model_dump(),
        cases=list(record.cases),
        metadata=record.metadata,
    )


def run_summary(run: EvaluationRunRecord, dataset: EvaluationDatasetRecord | None) -> EvaluationRunSummary:
    return EvaluationRunSummary(
        id=run.id,
        dataset_id=run.dataset_id,
        dataset_name=dataset.name if dataset else "Deleted dataset",
        status=run.status,
        stage=run.stage,
        progress_pct=run.progress_pct,
        case_count=run.case_count,
        completed_count=run.completed_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        summary=run.summary_json,
        group_path=run.group_path,
        document_ids=list(run.document_ids),
        error_code=run.error_code,
        error_message=run.error_message_safe,
        created_at=_iso(run.created_at),
        updated_at=_iso(run.updated_at),
        started_at=_iso(run.started_at),
        completed_at=_iso(run.completed_at),
        last_heartbeat_at=_iso(run.last_heartbeat_at),
    )


def run_detail(
    run: EvaluationRunRecord,
    dataset: EvaluationDatasetRecord | None,
    results: list[EvaluationCaseResultRecord],
) -> EvaluationRunDetail:
    summary = run_summary(run, dataset)
    return EvaluationRunDetail(
        **summary.model_dump(),
        cases=[case_result_response(result) for result in results],
        rag_config_snapshot=run.rag_config_snapshot,
        failure_breakdown=dict(run.summary_json.get("failure_breakdown") or {}),
        attempt_count=run.attempt_count,
        max_attempts=run.max_attempts,
    )


def case_result_response(record: EvaluationCaseResultRecord) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        id=record.id,
        run_id=record.run_id,
        case_id=record.case_id,
        case_index=record.case_index,
        question=record.question,
        status=record.status,  # type: ignore[arg-type]
        passed=record.passed,
        primary_failure_stage=record.primary_failure_stage,  # type: ignore[arg-type]
        failure_stages=list(record.failure_stages),  # type: ignore[arg-type]
        checks=record.checks_json,
        answer=record.answer,
        sources=list(record.sources_json),
        diagnostic=record.diagnostic_json,
        trace_id=record.trace_id,
        node_timings=list(record.node_timings_json),
        faithfulness_score=record.faithfulness_score,
        faithfulness_status=record.faithfulness_status,
        unfounded_claims=list(record.unfounded_claims),
        degraded=record.degraded,
        degraded_reason=record.degraded_reason,
        latency_ms=record.latency_ms,
        error_message=record.error_message_safe,
        created_at=_iso(record.created_at),
    )


def _select_cases(
    dataset: EvaluationDatasetRecord,
    *,
    case_ids: list[str],
    limit: int | None,
) -> list[Any]:
    cases = list(dataset.cases)
    if case_ids:
        allowed = set(case_ids)
        cases = [case for case in cases if case.id in allowed]
    if limit is not None:
        cases = cases[:limit]
    return cases


def _rag_config_snapshot() -> dict[str, Any]:
    config = effective_rag_config()
    return rag_config_response(config).model_dump(mode="json")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def default_evaluation_service() -> EvaluationService:
    from ..core.config import settings
    from ..repositories.evaluations import get_evaluation_repository
    from .queue import get_evaluation_run_queue

    return EvaluationService(
        repo_factory=get_evaluation_repository,
        queue_factory=get_evaluation_run_queue,
        retention_days=settings.evaluation_retention_days,
    )


def get_evaluation_service() -> EvaluationService:
    return default_evaluation_service()
