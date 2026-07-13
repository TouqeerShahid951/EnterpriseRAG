"""Application service for artifact-job submission and user actions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ..auth.context import UserContext
from ..query.schemas import QueryRequest
from .contracts import ArtifactContentBundle, DocumentPlan, EvidenceManifest
from .generated_models import GeneratedArtifactRepository
from .job_models import ArtifactJobRecord, ArtifactJobRepository
from .queue import ArtifactJobQueue
from .schemas import (
    ArtifactJobDetail,
    ArtifactJobStageProgress,
    ArtifactJobSummary,
    GeneratedArtifact,
)
from .types import ArtifactFormat


_PUBLIC_ERROR_MESSAGES = {
    "artifact_attempts_exhausted": "Document generation exhausted its retry limit.",
    "artifact_authorization_changed": "Authorization changed while the document was being generated.",
    "artifact_context_rejected": "The generation context was rejected by the backend.",
    "artifact_enqueue_failed": "Document generation could not be queued.",
    "artifact_format_failed": "One requested output format could not be generated.",
    "artifact_generation_failed": "Document generation failed. You can retry the job.",
    "artifact_no_evidence": "No authorized evidence was found for this document generation request.",
    "artifact_publish_warning": "The artifact was generated with a non-blocking publication warning.",
    "artifact_timeout": "Document generation timed out. You can retry the job.",
}


class ArtifactJobActionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ArtifactJobService:
    def __init__(
        self,
        *,
        repo_factory: Callable[[], ArtifactJobRepository],
        artifact_repo_factory: Callable[[], GeneratedArtifactRepository],
        queue_factory: Callable[[], ArtifactJobQueue],
        retention_days: int,
    ) -> None:
        self.repo_factory = repo_factory
        self.artifact_repo_factory = artifact_repo_factory
        self.queue_factory = queue_factory
        self.retention_days = retention_days

    def submit(
        self,
        *,
        request: QueryRequest,
        user: UserContext,
        trace_id: str,
        session_id: str,
        formats: tuple[ArtifactFormat, ...],
        conversation_context: list[dict[str, object]],
        seeded_plan: DocumentPlan | None = None,
        seeded_evidence: EvidenceManifest | None = None,
        seeded_bundle: ArtifactContentBundle | None = None,
    ) -> ArtifactJobSummary:
        repo = self.repo_factory()
        client_request_id = request.client_request_id or trace_id
        existing = repo.get_job_by_client_request(
            user_id=user.user_id,
            permission_version=user.permission_version,
            client_request_id=client_request_id,
        )
        if existing is not None:
            if existing.expires_at is not None and existing.expires_at <= datetime.now(
                UTC
            ):
                raise ArtifactJobActionError(
                    "artifact_job_expired",
                    "This generation request has expired. Submit it again with a new request ID.",
                )
            if existing.status == "queued":
                self._enqueue_or_fail(repo, existing.id)
            return self.summary(existing)
        job = repo.create_job(
            client_request_id=client_request_id,
            user_id=user.user_id,
            permission_version=user.permission_version,
            user_email=user.email,
            account_type=user.account_type,
            group_paths=list(user.group_paths),
            clearance_level=user.clearance_level,
            session_id=session_id,
            trace_id=trace_id,
            original_request=request.query,
            requested_formats=list(formats),
            group_path=request.group_path,
            document_ids=request.document_ids,
            conversation_context=conversation_context,
            retention_days=self.retention_days,
        )
        if (
            seeded_plan is not None
            and seeded_evidence is not None
            and seeded_bundle is not None
        ):
            updated = repo.update_job(
                job.id,
                {
                    "plan_json": seeded_plan.model_dump(mode="json"),
                    "evidence_manifest_json": seeded_evidence.model_dump(mode="json"),
                    "content_spec_json": seeded_bundle.model_dump(mode="json"),
                    "prompt_versions": {"artifact_seed": "grounded-rag-response-v1"},
                },
            )
            job = updated or job
        self._enqueue_or_fail(repo, job.id)
        return self.summary(job)

    def get_for_user(self, job_id: str, user: UserContext) -> ArtifactJobDetail:
        job = self._owned_job(job_id, user)
        summary = self.summary(job)
        plan = DocumentPlan.model_validate(job.plan_json) if job.plan_json else None
        return ArtifactJobDetail(
            **summary.model_dump(),
            original_request=job.original_request,
            group_path=job.group_path,
            document_ids=list(job.document_ids),
            plan=plan,
            evidence_manifest=job.evidence_manifest_json,
            content_specification=job.content_spec_json,
            validation_results=job.validation_results_json,
            stage_timings=_public_stage_timings(job.stage_timings_json),
            errors=_public_errors(job.errors_json),
        )

    def add_clarifications(
        self, job_id: str, user: UserContext, answers: dict[str, str]
    ) -> ArtifactJobSummary:
        job = self._owned_job(job_id, user)
        if job.status != "needs_input":
            raise ArtifactJobActionError(
                "artifact_job_not_waiting", "This job is not waiting for clarification."
            )
        cleaned = {
            question.strip(): answer.strip()
            for question, answer in answers.items()
            if question.strip() and answer.strip()
        }
        if not cleaned:
            raise ArtifactJobActionError(
                "artifact_clarification_empty",
                "At least one clarification answer is required.",
            )
        plan = DocumentPlan.model_validate(job.plan_json) if job.plan_json else None
        expected_questions = set(plan.clarification_questions if plan else [])
        unknown_questions = set(cleaned) - expected_questions
        if not expected_questions or unknown_questions:
            raise ArtifactJobActionError(
                "artifact_clarification_invalid",
                "Clarification answers must match the questions requested for this job.",
            )
        updated = self.repo_factory().update_job(
            job.id,
            {
                "clarifications": {**job.clarifications, **cleaned},
                "status": "queued",
                "stage": "queued",
                "progress_pct": 0,
                "stage_progress": None,
                "attempt_count": max(0, job.attempt_count - 1),
                "error_code": None,
                "error_message_safe": None,
            },
        )
        if updated is None:
            raise ArtifactJobActionError(
                "artifact_job_not_found", "Artifact job was not found."
            )
        self._enqueue_or_fail(self.repo_factory(), job.id)
        return self.summary(updated)

    def cancel(self, job_id: str, user: UserContext) -> ArtifactJobSummary:
        job = self._owned_job(job_id, user)
        if job.status in {"complete", "partial", "failed", "cancelled"}:
            return self.summary(job)
        updated = self.repo_factory().update_job(
            job.id,
            {
                "cancellation_requested": True,
                "status": "cancelled",
                "stage": "cancelled",
                "progress_pct": 100,
                "stage_progress": None,
                "completed_at": datetime.now(UTC),
            },
        )
        return self.summary(updated or job)

    def retry(self, job_id: str, user: UserContext) -> ArtifactJobSummary:
        job = self._owned_job(job_id, user)
        if job.status not in {"failed", "partial", "cancelled"}:
            raise ArtifactJobActionError(
                "artifact_job_not_retryable",
                "Only failed, partial, or cancelled jobs can be retried.",
            )
        if job.attempt_count >= job.max_attempts:
            raise ArtifactJobActionError(
                "artifact_retry_exhausted", "This job has reached its retry limit."
            )
        updated = self.repo_factory().update_job(
            job.id,
            {
                "status": "queued",
                "stage": "queued",
                "progress_pct": 0,
                "stage_progress": None,
                "cancellation_requested": False,
                "error_code": None,
                "error_message_safe": None,
                "started_at": None,
                "completed_at": None,
                "last_heartbeat_at": None,
            },
        )
        if updated is None:
            raise ArtifactJobActionError(
                "artifact_job_not_found", "Artifact job was not found."
            )
        self._enqueue_or_fail(self.repo_factory(), job.id)
        return self.summary(updated)

    def summary(self, job: ArtifactJobRecord) -> ArtifactJobSummary:
        artifact_records = (
            self.artifact_repo_factory().list_artifacts_for_job(job.id)
            if job.status in {"complete", "partial"}
            else []
        )
        artifacts = [
            GeneratedArtifact(
                id=record.id,
                filename=record.filename,
                format=record.format,  # type: ignore[arg-type]
                content_type=record.content_type,
                size_bytes=record.size_bytes,
                download_url=f"/api/v1/query/artifacts/{record.id}/content",
                created_at=record.created_at.isoformat() if record.created_at else None,
            )
            for record in artifact_records
        ]
        plan = DocumentPlan.model_validate(job.plan_json) if job.plan_json else None
        stage_progress = _artifact_stage_progress(job.stage_progress)
        stage_label, stage_detail = _artifact_stage_copy(job, stage_progress)
        return ArtifactJobSummary(
            id=job.id,
            status=job.status,
            stage=job.stage,
            progress_pct=job.progress_pct,
            stage_label=stage_label,
            stage_detail=stage_detail,
            stage_progress=stage_progress,
            requested_formats=list(job.requested_formats),  # type: ignore[arg-type]
            clarification_questions=plan.clarification_questions if plan else [],
            artifacts=artifacts,
            error_code=job.error_code,
            error_message=job.error_message_safe,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            created_at=job.created_at.isoformat() if job.created_at else None,
            updated_at=job.updated_at.isoformat() if job.updated_at else None,
            started_at=job.started_at.isoformat() if job.started_at else None,
            completed_at=job.completed_at.isoformat() if job.completed_at else None,
            last_heartbeat_at=job.last_heartbeat_at.isoformat()
            if job.last_heartbeat_at
            else None,
            expires_at=job.expires_at.isoformat() if job.expires_at else None,
        )

    def _owned_job(self, job_id: str, user: UserContext) -> ArtifactJobRecord:
        job = self.repo_factory().get_job(job_id)
        if (
            job is None
            or job.user_id != user.user_id
            or job.permission_version != user.permission_version
            or (job.expires_at is not None and job.expires_at <= datetime.now(UTC))
        ):
            raise ArtifactJobActionError(
                "artifact_job_not_found", "Artifact job was not found."
            )
        return job

    def _enqueue_or_fail(self, repo: ArtifactJobRepository, job_id: str) -> None:
        try:
            self.queue_factory().enqueue(job_id)
        except RuntimeError as exc:
            repo.update_job(
                job_id,
                {
                    "status": "failed",
                    "stage": "failed",
                    "progress_pct": 100,
                    "stage_progress": None,
                    "error_code": "artifact_enqueue_failed",
                    "error_message_safe": "Document generation could not be queued.",
                    "completed_at": datetime.now(UTC),
                },
            )
            raise ArtifactJobActionError(
                "artifact_enqueue_failed", "Document generation could not be queued."
            ) from exc


def _artifact_stage_progress(
    payload: dict[str, object] | None,
) -> ArtifactJobStageProgress | None:
    if not payload:
        return None
    try:
        return ArtifactJobStageProgress.model_validate(payload)
    except Exception:
        return None


def _artifact_stage_copy(
    job: ArtifactJobRecord,
    progress: ArtifactJobStageProgress | None,
) -> tuple[str, str]:
    formats = ", ".join(format_name(item) for item in job.requested_formats)
    if job.status == "queued":
        return "Queued", "Waiting for the document generation worker"
    if job.status == "needs_input":
        return "Needs input", "Answer the clarification questions to continue"
    if job.status == "complete":
        return "Complete", f"Generated {formats or 'requested files'}"
    if job.status == "partial":
        return (
            "Partially complete",
            job.error_message_safe
            or f"Some {formats or 'files'} could not be generated",
        )
    if job.status == "failed":
        return "Failed", job.error_message_safe or "Document generation failed"
    if job.status == "cancelled":
        return "Cancelled", "Document generation was cancelled"

    if job.stage == "planning":
        return "Planning document", "Planning document structure"
    if job.stage == "retrieving":
        return "Retrieving evidence", "Collecting evidence from permitted documents"
    if job.stage == "formatting_outputs":
        return "Formatting output", "Choosing title, sections, and slide layout"
    if job.stage == "validating":
        return "Validating grounding", "Checking evidence grounding"
    if job.stage == "storing":
        return "Saving file", "Saving generated file"
    if job.stage.startswith("composing_") and progress:
        return (
            "Composing content",
            progress.label
            or f"Composing content batch {progress.current} of {progress.total}",
        )
    if job.stage.startswith("rendering_") and progress:
        return (
            "Rendering files",
            progress.label or f"Rendering {formats or 'requested files'}",
        )
    if job.stage == "rendering":
        return "Rendering files", f"Rendering {formats or 'requested files'}"
    if job.stage == "composing":
        return "Composing content", "Composing evidence-backed content"
    return _humanize(job.status), _humanize(job.stage)


def format_name(value: str) -> str:
    return value.upper()


def _humanize(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split("_") if part)


def _public_stage_timings(
    payload: dict[str, object] | None,
) -> dict[str, dict[str, object]]:
    timings: dict[str, dict[str, object]] = {}
    if not payload:
        return timings
    for stage, raw_timing in payload.items():
        if not isinstance(raw_timing, dict):
            continue
        duration = raw_timing.get("duration_ms")
        try:
            duration_ms = max(0, int(duration))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        timing: dict[str, object] = {"duration_ms": duration_ms}
        for field in ("started_at", "completed_at"):
            value = raw_timing.get(field)
            if value is None or isinstance(value, str):
                timing[field] = value
        timings[str(stage)] = timing
    return timings


def _public_errors(payload: tuple[dict[str, object], ...]) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for raw_error in payload:
        code = str(raw_error.get("code") or "artifact_generation_failed")
        public_error: dict[str, object] = {
            "stage": str(raw_error.get("stage") or "generation"),
            "code": code,
            "message": _PUBLIC_ERROR_MESSAGES.get(
                code,
                "Document generation encountered an error.",
            ),
        }
        recorded_at = raw_error.get("recorded_at")
        if isinstance(recorded_at, str):
            public_error["recorded_at"] = recorded_at
        errors.append(public_error)
    return errors
