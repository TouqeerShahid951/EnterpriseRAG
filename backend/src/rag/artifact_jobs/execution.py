"""Durable artifact-job execution orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import logging
from time import perf_counter

from ..auth.document_access import can_read_document
from ..core.config import Settings
from ..query.inference import InferenceClient
from ..query.qdrant import QdrantClient
from ..repositories.artifact_jobs import ArtifactJobRecord, ArtifactJobRepository
from ..repositories.document_models import DocumentRepository
from ..repositories.generated_artifact_models import GeneratedArtifactRepository
from ..repositories.identity_models import IdentityRepository, UserRecord
from ..repositories.rag_config_models import RagConfigRecord
from ..services.generated_artifact_storage import GeneratedArtifactStorage
from .composer import (
    COMPOSER_PROMPT_VERSION,
    FORMATTER_PROMPT_VERSION,
    compose_document_bundle,
    fallback_repair_document_bundle,
    normalize_bundle_evidence_ids,
    repair_document_bundle,
)
from .llm_json import LlmContractError
from .contracts import ArtifactContentBundle, DocumentPlan, EvidenceManifest
from .planner import PLANNER_PROMPT_VERSION, plan_document
from .renderer import render_document
from .retrieval import retrieve_document_evidence
from .validation import validate_document_bundle


logger = logging.getLogger("rag.artifact_jobs")


class ArtifactPermissionChanged(RuntimeError):
    pass


class ArtifactJobCancelled(RuntimeError):
    pass


class ArtifactEvidenceUnavailable(RuntimeError):
    safe_message = "No authorized evidence was found for this document generation request."


class ArtifactJobExecutor:
    def __init__(
        self,
        *,
        config: Settings,
        repo_factory: Callable[[], ArtifactJobRepository],
        artifact_repo_factory: Callable[[], GeneratedArtifactRepository],
        storage_factory: Callable[[], GeneratedArtifactStorage],
        identity_repo_factory: Callable[[], IdentityRepository],
        document_repo_factory: Callable[[], DocumentRepository],
        inference: InferenceClient,
        qdrant: QdrantClient,
        model_name: str,
        rag_config: RagConfigRecord,
    ) -> None:
        self.config = config
        self.repo_factory = repo_factory
        self.artifact_repo_factory = artifact_repo_factory
        self.storage_factory = storage_factory
        self.identity_repo_factory = identity_repo_factory
        self.document_repo_factory = document_repo_factory
        self.inference = inference
        self.qdrant = qdrant
        self.model_name = model_name
        self.rag_config = rag_config

    def execute(self, job_id: str) -> ArtifactJobRecord:
        repo = self.repo_factory()
        job, accepted = repo.start_attempt(job_id)
        if job is None:
            raise RuntimeError("artifact job was not found")
        if not accepted:
            return job
        if job.plan_json and job.evidence_manifest_json and job.content_spec_json:
            return self._execute_seeded_response_job(job)
        with self._stage_timer(job.id, "planning"):
            self._authorize(job)
            self._check_cancelled(job.id)
            plan = plan_document(job, inference=self.inference, model=self.model_name)
            job = self._update(job.id, {
                "plan_json": plan.model_dump(mode="json"),
                "model_versions": {
                    "planner": self.model_name,
                    "composer": self.model_name,
                },
                "prompt_versions": {
                    "planner": PLANNER_PROMPT_VERSION,
                    "composer": COMPOSER_PROMPT_VERSION,
                    "formatter": FORMATTER_PROMPT_VERSION,
                },
                "stage_progress": _progress("sections", 0, len(plan.sections), "Planning document structure"),
            })
            if plan.clarification_questions:
                return self._update(job.id, {
                    "status": "needs_input",
                    "stage": "needs_input",
                    "progress_pct": 10,
                    "stage_progress": None,
                })

        self._check_cancelled(job.id)
        self._update(job.id, {
            "status": "retrieving",
            "stage": "retrieving",
            "progress_pct": 20,
            "stage_progress": _progress("sections", 0, len(plan.sections), "Collecting evidence from permitted documents"),
        })
        with self._stage_timer(job.id, "retrieving"):
            started_at = perf_counter()
            evidence = retrieve_document_evidence(
                job,
                plan,
                inference=self.inference,
                qdrant=self.qdrant,
                config=self.config,
                rag_config=self.rag_config,
                document_repo=self.document_repo_factory(),
            )
            logger.info(
                "artifact retrieval completed job_id=%s sections=%d records=%d duration_ms=%d",
                job.id,
                len(evidence.sections),
                len(evidence.records),
                int((perf_counter() - started_at) * 1000),
            )
            job = self._update(job.id, {
                "evidence_manifest_json": evidence.model_dump(mode="json"),
                "progress_pct": 50,
                "stage_progress": _progress("sections", len(evidence.sections), len(plan.sections), "Collected evidence"),
            })
            if not evidence.records:
                self._record_error(
                    job.id,
                    stage="retrieving",
                    code="artifact_no_evidence",
                    message=ArtifactEvidenceUnavailable.safe_message,
                )
                raise ArtifactEvidenceUnavailable(ArtifactEvidenceUnavailable.safe_message)

        self._check_cancelled(job.id)
        self._update(job.id, {
            "status": "composing",
            "stage": "composing",
            "progress_pct": 55,
            "stage_progress": _progress("batches", 0, 1, "Preparing content composition"),
        })
        with self._stage_timer(job.id, "composing"):
            started_at = perf_counter()
            bundle = compose_document_bundle(
                job,
                plan,
                evidence,
                inference=self.inference,
                model=self.model_name,
                section_timeout_seconds=self.config.artifact_composer_timeout_seconds,
                progress_callback=lambda current, total, phase: self._record_composition_progress(
                    job.id,
                    current=current,
                    total=total,
                    phase=phase,
                ),
            )
            logger.info(
                "artifact composition completed job_id=%s content_sections=%d slides=%d duration_ms=%d",
                job.id,
                len(bundle.content.sections),
                len(bundle.presentation.slides),
                int((perf_counter() - started_at) * 1000),
            )
        self._update(job.id, {
            "content_spec_json": bundle.model_dump(mode="json"),
            "status": "validating",
            "stage": "validating",
            "progress_pct": 72,
            "stage_progress": None,
        })
        with self._stage_timer(job.id, "validating"):
            validation = validate_document_bundle(bundle, plan=plan, evidence=evidence)
            self._update(job.id, {"validation_results_json": validation.model_dump(mode="json")})
            if not validation.passed:
                bundle = self._repair_or_fallback_bundle(job.id, bundle, validation.errors, evidence, plan)
                validation = validate_document_bundle(bundle, plan=plan, evidence=evidence)
                self._update(job.id, {"validation_results_json": validation.model_dump(mode="json")})
            if not validation.passed:
                self._record_error(
                    job.id,
                    stage="validating",
                    code="artifact_content_validation_failed",
                    message="; ".join(validation.errors[:8]),
                )
                raise RuntimeError("artifact content validation failed: " + "; ".join(validation.errors[:8]))
        job = self._update(job.id, {
            "content_spec_json": bundle.model_dump(mode="json"),
            "status": "rendering",
            "stage": "rendering",
            "progress_pct": 80,
            "stage_progress": _progress("formats", 0, len(job.requested_formats), "Preparing requested files"),
        })
        with self._stage_timer(job.id, "rendering"):
            failures = self._render_formats(job, evidence, bundle)
        status = (
            "complete"
            if not failures
            else ("partial" if len(failures) < len(job.requested_formats) else "failed")
        )
        return self._update(job.id, {
            "status": status,
            "stage": status,
            "progress_pct": 100,
            "stage_progress": None,
            "error_code": "artifact_format_failures" if failures else None,
            "error_message_safe": f"Failed formats: {', '.join(failures)}" if failures else None,
            "completed_at": datetime.now(UTC),
        })

    def _execute_seeded_response_job(self, job: ArtifactJobRecord) -> ArtifactJobRecord:
        with self._stage_timer(job.id, "planning"):
            self._authorize(job)
            self._check_cancelled(job.id)
            plan = DocumentPlan.model_validate(job.plan_json)
            evidence = EvidenceManifest.model_validate(job.evidence_manifest_json)
            bundle = normalize_bundle_evidence_ids(
                ArtifactContentBundle.model_validate(job.content_spec_json),
                evidence,
            )
            job = self._update(job.id, {
                "model_versions": {"artifact_seed": "normal_rag_response"},
                "prompt_versions": {**job.prompt_versions, "artifact_seed": "grounded-rag-response-v1"},
                "content_spec_json": bundle.model_dump(mode="json"),
                "progress_pct": 70,
                "stage_progress": _progress("files", 0, len(job.requested_formats), "Preparing grounded response file"),
            })

        self._check_cancelled(job.id)
        self._update(job.id, {"status": "validating", "stage": "validating", "progress_pct": 72, "stage_progress": None})
        with self._stage_timer(job.id, "validating"):
            validation = validate_document_bundle(bundle, plan=plan, evidence=evidence)
            self._update(job.id, {"validation_results_json": validation.model_dump(mode="json")})
            if not validation.passed:
                bundle = self._repair_or_fallback_bundle(job.id, bundle, validation.errors, evidence, plan)
                validation = validate_document_bundle(bundle, plan=plan, evidence=evidence)
                self._update(job.id, {
                    "content_spec_json": bundle.model_dump(mode="json"),
                    "validation_results_json": validation.model_dump(mode="json"),
                })
            if not validation.passed:
                self._record_error(
                    job.id,
                    stage="validating",
                    code="artifact_seed_validation_failed",
                    message="; ".join(validation.errors[:8]),
                )
                raise RuntimeError("artifact seeded content validation failed: " + "; ".join(validation.errors[:8]))

        job = self._update(job.id, {
            "status": "rendering",
            "stage": "rendering",
            "progress_pct": 80,
            "stage_progress": _progress("formats", 0, len(job.requested_formats), "Preparing requested files"),
        })
        with self._stage_timer(job.id, "rendering"):
            failures = self._render_formats(job, evidence, bundle)
        status = (
            "complete"
            if not failures
            else ("partial" if len(failures) < len(job.requested_formats) else "failed")
        )
        return self._update(job.id, {
            "status": status,
            "stage": status,
            "progress_pct": 100,
            "stage_progress": None,
            "error_code": "artifact_format_failures" if failures else None,
            "error_message_safe": f"Failed formats: {', '.join(failures)}" if failures else None,
            "completed_at": datetime.now(UTC),
        })

    def _render_formats(
        self,
        job: ArtifactJobRecord,
        evidence: EvidenceManifest,
        bundle: ArtifactContentBundle,
    ) -> list[str]:
        source_doc_ids = list(dict.fromkeys(record.doc_id for record in evidence.records))
        return self._render_deterministic_formats(job, bundle, source_doc_ids, list(job.requested_formats))

    def _render_deterministic_formats(
        self,
        job: ArtifactJobRecord,
        bundle: ArtifactContentBundle,
        source_doc_ids: list[str],
        requested_formats: list[str],
    ) -> list[str]:
        failures: list[str] = []
        total_formats = max(len(requested_formats), 1)
        for index, artifact_format in enumerate(requested_formats, start=1):
            try:
                self._check_cancelled(job.id)
                self._authorize(job)
                self._record_render_format_progress(job.id, artifact_format, index, total_formats)
                rendered = render_document(
                    artifact_format=artifact_format,  # type: ignore[arg-type]
                    bundle=bundle,
                    generated_at=datetime.now(UTC),
                    require_libreoffice=self.config.artifact_libreoffice_required,
                    progress_callback=(
                        lambda current, total, label, fmt=artifact_format, fmt_index=index, fmt_total=total_formats:
                        self._record_slide_progress(job.id, fmt, fmt_index, fmt_total, current, total, label)
                    ) if artifact_format == "pptx" else None,
                )
                self._store_rendered_file(
                    job=job,
                    filename=rendered.filename,
                    artifact_format=rendered.format,
                    content_type=rendered.content_type,
                    content=rendered.content,
                    source_doc_ids=source_doc_ids,
                    warnings=list(rendered.smoke_warnings),
                    progress_pct=_format_complete_progress(index, total_formats),
                )
            except Exception as exc:
                failures.append(artifact_format)
                self._record_format_error(job.id, artifact_format, exc)
        return failures

    def _store_rendered_file(
        self,
        *,
        job: ArtifactJobRecord,
        filename: str,
        artifact_format: str,
        content_type: str,
        content: bytes,
        source_doc_ids: list[str],
        warnings: list[str],
        progress_pct: int,
    ) -> None:
        with self._stage_timer(job.id, "storing", accumulate=True):
            self._update(job.id, {
                "status": "rendering",
                "stage": "storing",
                "progress_pct": progress_pct,
                "stage_progress": _progress("files", 0, 1, f"Saving {artifact_format.upper()} file"),
            })
            stored = self.storage_factory().put(
                filename=filename,
                content=content,
                content_type=content_type,
            )
            record = self.artifact_repo_factory().create_artifact(
                job_id=job.id,
                user_id=job.user_id,
                permission_version=job.permission_version,
                session_id=job.session_id,
                trace_id=job.trace_id,
                requested_formats=list(job.requested_formats),
                filename=filename,
                format=artifact_format,
                content_type=content_type,
                object_path=stored.object_path,
                size_bytes=stored.size_bytes,
                source_doc_ids=source_doc_ids,
                prompt=job.original_request,
            )
            self.document_repo_factory().append_audit_event(
                event_type="query.artifact_created",
                actor_id=job.user_id,
                target_type="generated_artifact",
                target_id=record.id,
                payload={
                    "artifact_job_id": job.id,
                    "format": artifact_format,
                    "source_doc_ids": source_doc_ids,
                    "smoke_warnings": warnings,
                },
            )

    def _record_format_error(self, job_id: str, artifact_format: str, exc: Exception) -> None:
        detail = str(exc)[:2000]
        self._record_error(
            job_id,
            stage="rendering",
            code="artifact_format_failed",
            message=f"{artifact_format}: {type(exc).__name__}: {detail}",
            context={"format": artifact_format},
        )
        logger.warning(
            "artifact format failed job_id=%s format=%s error_type=%s error=%s",
            job_id,
            artifact_format,
            type(exc).__name__,
            detail,
        )

    def _authorize(self, job: ArtifactJobRecord) -> UserRecord:
        user = self.identity_repo_factory().get_user_by_id(job.user_id)
        if user is None or not user.is_active or user.permission_version != job.permission_version:
            raise ArtifactPermissionChanged("artifact job authorization is no longer valid")
        document_repo = self.document_repo_factory()
        for document_id in job.document_ids:
            document = document_repo.get_document(document_id)
            if document is None or not can_read_document(user, document):
                raise ArtifactPermissionChanged("artifact job document access is no longer valid")
        return user

    def _check_cancelled(self, job_id: str) -> None:
        current = self.repo_factory().get_job(job_id)
        if current is None:
            raise RuntimeError("artifact job was not found")
        if current.cancellation_requested or current.status == "cancelled":
            raise ArtifactJobCancelled("artifact job was cancelled")

    def _update(self, job_id: str, changes: dict[str, object]) -> ArtifactJobRecord:
        updated = self.repo_factory().update_job(job_id, changes)
        if updated is None:
            raise RuntimeError("artifact job was not found")
        return updated

    def _record_composition_progress(self, job_id: str, *, current: int, total: int, phase: str) -> None:
        bounded_total = max(total, 1)
        bounded_current = min(max(current, 0), bounded_total)
        if phase == "formatting":
            changes = {
                "status": "composing",
                "stage": "formatting_outputs",
                "progress_pct": 70,
                "stage_progress": _progress("slides", 0, 1, "Choosing title, sections, and slide layout"),
            }
        else:
            if phase == "batch_complete":
                progress = 56 + int((bounded_current / bounded_total) * 14)
            else:
                progress = 56 + int(((max(bounded_current, 1) - 1) / bounded_total) * 14)
            changes = {
                "status": "composing",
                "stage": f"composing_{max(bounded_current, 1)}_of_{bounded_total}_batch",
                "progress_pct": min(70, max(56, progress)),
                "stage_progress": _progress(
                    "batches",
                    bounded_current,
                    bounded_total,
                    f"Composing content batch {bounded_current} of {bounded_total}",
                ),
            }
        try:
            self._update(job_id, changes)
        except Exception:
            logger.warning(
                "failed to record artifact composition progress job_id=%s phase=%s current=%s total=%s",
                job_id,
                phase,
                current,
                total,
                exc_info=True,
            )

    def _record_render_format_progress(self, job_id: str, artifact_format: str, current: int, total: int) -> None:
        pct = 80 + int((max(current - 1, 0) / max(total, 1)) * 15)
        self._update(job_id, {
            "status": "rendering",
            "stage": f"rendering_{artifact_format}",
            "progress_pct": min(95, max(80, pct)),
            "stage_progress": _progress(
                "formats",
                current,
                max(total, 1),
                f"Rendering {artifact_format.upper()} ({current} of {max(total, 1)})",
            ),
        })

    def _record_slide_progress(
        self,
        job_id: str,
        artifact_format: str,
        format_current: int,
        format_total: int,
        slide_current: int,
        slide_total: int,
        label: str,
    ) -> None:
        format_span = 15 / max(format_total, 1)
        format_start = 80 + ((max(format_current, 1) - 1) * format_span)
        pct = int(format_start + (min(max(slide_current, 0), max(slide_total, 1)) / max(slide_total, 1)) * format_span)
        self._update(job_id, {
            "status": "rendering",
            "stage": f"rendering_{artifact_format}_slide",
            "progress_pct": min(95, max(82, pct)),
            "stage_progress": _progress(
                "slides",
                slide_current,
                max(slide_total, 1),
                f"Building slide {slide_current} of {max(slide_total, 1)}: {label}",
            ),
        })

    def _repair_or_fallback_bundle(
        self,
        job_id: str,
        bundle: ArtifactContentBundle,
        errors: list[str],
        evidence: EvidenceManifest,
        plan: DocumentPlan,
    ) -> ArtifactContentBundle:
        fallback = normalize_bundle_evidence_ids(
            fallback_repair_document_bundle(bundle, errors=errors, evidence=evidence),
            evidence,
        )
        fallback_validation = validate_document_bundle(fallback, plan=plan, evidence=evidence)
        if fallback_validation.passed:
            return fallback
        try:
            repaired = repair_document_bundle(
                bundle,
                errors=errors,
                evidence=evidence,
                inference=self.inference,
                model=self.model_name,
            )
        except LlmContractError as exc:
            logger.warning(
                "artifact repair fallback job_id=%s error_type=%s",
                job_id,
                type(exc).__name__,
            )
            self._record_error(
                job_id,
                stage="validating",
                code="artifact_repair_contract_failed",
                message=str(exc)[:400],
            )
            return fallback
        return normalize_bundle_evidence_ids(repaired, evidence)

    @contextmanager
    def _stage_timer(self, job_id: str, stage: str, *, accumulate: bool = False) -> Iterator[None]:
        started_at = datetime.now(UTC)
        started_perf = perf_counter()
        try:
            yield
        finally:
            try:
                self._record_stage_timing(
                    job_id,
                    stage,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    duration_ms=int((perf_counter() - started_perf) * 1000),
                    accumulate=accumulate,
                )
            except Exception:
                logger.warning(
                    "failed to record artifact stage timing job_id=%s stage=%s",
                    job_id,
                    stage,
                    exc_info=True,
                )

    def _record_stage_timing(
        self,
        job_id: str,
        stage: str,
        *,
        started_at: datetime,
        completed_at: datetime,
        duration_ms: int,
        accumulate: bool,
    ) -> None:
        repo = self.repo_factory()
        current = repo.get_job(job_id)
        if current is None:
            return
        timings = dict(current.stage_timings_json)
        timing: dict[str, object] = {
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": max(0, duration_ms),
        }
        existing = timings.get(stage)
        if accumulate and isinstance(existing, dict):
            timing["started_at"] = str(existing.get("started_at") or timing["started_at"])
            try:
                timing["duration_ms"] = int(existing.get("duration_ms") or 0) + int(timing["duration_ms"])
            except (TypeError, ValueError):
                pass
        timings[stage] = timing
        repo.update_job(job_id, {"stage_timings_json": timings})

    def _record_error(
        self,
        job_id: str,
        *,
        stage: str,
        code: str,
        message: str,
        context: dict[str, object] | None = None,
    ) -> None:
        repo = self.repo_factory()
        current = repo.get_job(job_id)
        if current is None:
            return
        errors = list(current.errors_json)
        errors.append({
            "stage": stage,
            "code": code,
            "message": message[:2000],
            "context": context or {},
            "recorded_at": datetime.now(UTC).isoformat(),
        })
        repo.update_job(job_id, {"errors_json": errors[-50:]})


def _progress(unit: str, current: int, total: int, label: str) -> dict[str, object]:
    return {
        "unit": unit,
        "current": max(0, current),
        "total": max(0, total),
        "label": label,
    }


def _format_complete_progress(current: int, total: int) -> int:
    return min(96, max(84, 80 + int((max(current, 1) / max(total, 1)) * 15)))


def default_artifact_job_executor(config: Settings | None = None) -> ArtifactJobExecutor:
    from ..core.config import settings
    from ..query.inference import build_inference_client
    from ..repositories.artifact_jobs import get_artifact_job_repository
    from ..repositories.documents import get_document_repository
    from ..repositories.generated_artifacts import get_generated_artifact_repository
    from ..repositories.identity import get_identity_repository
    from ..repositories.rag_config import effective_rag_config
    from ..services.generated_artifact_storage import get_generated_artifact_storage

    selected = config or settings
    rag_config = effective_rag_config(config=selected)
    inference = build_inference_client(rag_config, settings=selected)
    return ArtifactJobExecutor(
        config=selected,
        repo_factory=get_artifact_job_repository,
        artifact_repo_factory=get_generated_artifact_repository,
        storage_factory=get_generated_artifact_storage,
        identity_repo_factory=get_identity_repository,
        document_repo_factory=get_document_repository,
        inference=inference,
        qdrant=QdrantClient(
            base_url=selected.qdrant_url,
            collection=selected.qdrant_collection,
            timeout_seconds=selected.rag_http_timeout_seconds,
        ),
        model_name=rag_config.effective_reasoning_model or rag_config.chat_model,
        rag_config=rag_config,
    )
