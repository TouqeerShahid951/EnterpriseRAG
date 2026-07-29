"""Durable artifact-job execution orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import logging
from time import perf_counter
from uuid import uuid4

from rag.core.config import Settings
from rag.documents.models import DocumentRepository
from rag.auth.identity_models import IdentityRepository
from rag.retrieval.contracts import AuthorizedCorpusRetriever
from rag.artifact_jobs.execution.bundle_repair import (
    fallback_repair_document_bundle,
    normalize_bundle_evidence_ids,
    repair_document_bundle,
)
from rag.artifact_jobs.generation.composition import (
    COMPOSER_PROMPT_VERSION,
    compose_document_bundle,
)
from rag.artifact_jobs.generation.format_adaptation import FORMATTER_PROMPT_VERSION
from rag.artifact_jobs.generation.llm_json import LlmContractError
from rag.artifact_jobs.contracts import ArtifactContentBundle, DocumentPlan, EvidenceManifest
from rag.artifact_jobs.execution.errors import (
    ArtifactEvidenceUnavailable,
    ArtifactJobCancelled as ArtifactJobCancelled,
    ArtifactJobLeaseLost as ArtifactJobLeaseLost,
    ArtifactPermissionChanged as ArtifactPermissionChanged,
)
from rag.artifact_jobs.execution.progress import ArtifactExecutionProgress, _progress
from rag.artifact_jobs.execution.rendering import ArtifactFormatExecution
from rag.artifact_jobs.execution.state import ArtifactExecutionState
from rag.artifact_jobs.generated_models import GeneratedArtifactRepository
from rag.artifact_jobs.generation import ArtifactJsonGenerator
from rag.artifact_jobs.job_models import ArtifactJobRecord, ArtifactJobRepository
from rag.artifact_jobs.generation.planner import PLANNER_PROMPT_VERSION, plan_document
from rag.artifact_jobs.publisher import ArtifactPublisher
from rag.artifact_jobs.retrieval import retrieve_document_evidence
from rag.artifact_jobs.storage import GeneratedArtifactStorage
from rag.artifact_jobs.generation.validation import validate_document_bundle


logger = logging.getLogger("rag.artifact_jobs")


class ArtifactJobExecutor(
    ArtifactExecutionState,
    ArtifactExecutionProgress,
    ArtifactFormatExecution,
):
    def __init__(
        self,
        *,
        config: Settings,
        repo_factory: Callable[[], ArtifactJobRepository],
        artifact_repo_factory: Callable[[], GeneratedArtifactRepository],
        storage_factory: Callable[[], GeneratedArtifactStorage],
        identity_repo_factory: Callable[[], IdentityRepository],
        document_repo_factory: Callable[[], DocumentRepository],
        inference: ArtifactJsonGenerator,
        retriever: AuthorizedCorpusRetriever,
        model_name: str,
    ) -> None:
        self.config = config
        self.repo_factory = repo_factory
        self.artifact_repo_factory = artifact_repo_factory
        self.storage_factory = storage_factory
        self.identity_repo_factory = identity_repo_factory
        self.document_repo_factory = document_repo_factory
        self.publisher = ArtifactPublisher(
            artifact_repo_factory=artifact_repo_factory,
            storage_factory=storage_factory,
            audit_repo_factory=document_repo_factory,
        )
        self.inference = inference
        self.retriever = retriever
        self.model_name = model_name
        self._run_token: str | None = None

    def execute(
        self, job_id: str, *, run_token: str | None = None
    ) -> ArtifactJobRecord:
        self._run_token = run_token or str(uuid4())
        repo = self.repo_factory()
        job, accepted = repo.start_attempt(job_id, run_token=self._run_token)
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
            job = self._update(
                job.id,
                {
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
                    "stage_progress": _progress(
                        "sections", 0, len(plan.sections), "Planning document structure"
                    ),
                },
            )
            if plan.clarification_questions:
                return self._update(
                    job.id,
                    {
                        "status": "needs_input",
                        "stage": "needs_input",
                        "progress_pct": 10,
                        "stage_progress": None,
                    },
                )

        self._check_cancelled(job.id)
        self._update(
            job.id,
            {
                "status": "retrieving",
                "stage": "retrieving",
                "progress_pct": 20,
                "stage_progress": _progress(
                    "sections",
                    0,
                    len(plan.sections),
                    "Collecting evidence from permitted documents",
                ),
            },
        )
        with self._stage_timer(job.id, "retrieving"):
            started_at = perf_counter()
            evidence = retrieve_document_evidence(
                job,
                plan,
                retriever=self.retriever,
                document_repo=self.document_repo_factory(),
            )
            source_doc_ids = list(
                dict.fromkeys(record.doc_id for record in evidence.records)
            )
            self._authorize(job, source_doc_ids)
            logger.info(
                "artifact retrieval completed job_id=%s sections=%d records=%d duration_ms=%d",
                job.id,
                len(evidence.sections),
                len(evidence.records),
                int((perf_counter() - started_at) * 1000),
            )
            job = self._update(
                job.id,
                {
                    "evidence_manifest_json": evidence.model_dump(mode="json"),
                    "progress_pct": 50,
                    "stage_progress": _progress(
                        "sections",
                        len(evidence.sections),
                        len(plan.sections),
                        "Collected evidence",
                    ),
                },
            )
            if not evidence.records:
                self._record_error(
                    job.id,
                    stage="retrieving",
                    code="artifact_no_evidence",
                    message=ArtifactEvidenceUnavailable.safe_message,
                )
                raise ArtifactEvidenceUnavailable(
                    ArtifactEvidenceUnavailable.safe_message
                )

        self._check_cancelled(job.id)
        self._update(
            job.id,
            {
                "status": "composing",
                "stage": "composing",
                "progress_pct": 55,
                "stage_progress": _progress(
                    "batches", 0, 1, "Preparing content composition"
                ),
            },
        )
        with self._stage_timer(job.id, "composing"):
            started_at = perf_counter()
            bundle = compose_document_bundle(
                job,
                plan,
                evidence,
                inference=self.inference,
                model=self.model_name,
                section_timeout_seconds=self.config.artifact_composer_timeout_seconds,
                progress_callback=lambda current, total, phase: (
                    self._record_composition_progress(
                        job.id,
                        current=current,
                        total=total,
                        phase=phase,
                    )
                ),
            )
            logger.info(
                "artifact composition completed job_id=%s content_sections=%d slides=%d duration_ms=%d",
                job.id,
                len(bundle.content.sections),
                len(bundle.presentation.slides),
                int((perf_counter() - started_at) * 1000),
            )
        self._update(
            job.id,
            {
                "content_spec_json": bundle.model_dump(mode="json"),
                "status": "validating",
                "stage": "validating",
                "progress_pct": 72,
                "stage_progress": None,
            },
        )
        with self._stage_timer(job.id, "validating"):
            validation = validate_document_bundle(bundle, plan=plan, evidence=evidence)
            self._update(
                job.id, {"validation_results_json": validation.model_dump(mode="json")}
            )
            if not validation.passed:
                bundle = self._repair_or_fallback_bundle(
                    job.id, bundle, validation.errors, evidence, plan
                )
                validation = validate_document_bundle(
                    bundle, plan=plan, evidence=evidence
                )
                self._update(
                    job.id,
                    {"validation_results_json": validation.model_dump(mode="json")},
                )
            if not validation.passed:
                self._record_error(
                    job.id,
                    stage="validating",
                    code="artifact_content_validation_failed",
                    message="; ".join(validation.errors[:8]),
                )
                raise RuntimeError(
                    "artifact content validation failed: "
                    + "; ".join(validation.errors[:8])
                )
        job = self._update(
            job.id,
            {
                "content_spec_json": bundle.model_dump(mode="json"),
                "status": "rendering",
                "stage": "rendering",
                "progress_pct": 80,
                "stage_progress": _progress(
                    "formats",
                    0,
                    len(job.requested_formats),
                    "Preparing requested files",
                ),
            },
        )
        with self._stage_timer(job.id, "rendering"):
            failures = self._render_formats(job, evidence, bundle)
        status = (
            "complete"
            if not failures
            else ("partial" if len(failures) < len(job.requested_formats) else "failed")
        )
        return self._update(
            job.id,
            {
                "status": status,
                "stage": status,
                "progress_pct": 100,
                "stage_progress": None,
                "error_code": "artifact_format_failures" if failures else None,
                "error_message_safe": f"Failed formats: {', '.join(failures)}"
                if failures
                else None,
                "completed_at": datetime.now(UTC),
            },
        )

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
            job = self._update(
                job.id,
                {
                    "model_versions": {"artifact_seed": "normal_rag_response"},
                    "prompt_versions": {
                        **job.prompt_versions,
                        "artifact_seed": "grounded-rag-response-v1",
                    },
                    "content_spec_json": bundle.model_dump(mode="json"),
                    "progress_pct": 70,
                    "stage_progress": _progress(
                        "files",
                        0,
                        len(job.requested_formats),
                        "Preparing grounded response file",
                    ),
                },
            )

        self._check_cancelled(job.id)
        self._update(
            job.id,
            {
                "status": "validating",
                "stage": "validating",
                "progress_pct": 72,
                "stage_progress": None,
            },
        )
        with self._stage_timer(job.id, "validating"):
            validation = validate_document_bundle(bundle, plan=plan, evidence=evidence)
            self._update(
                job.id, {"validation_results_json": validation.model_dump(mode="json")}
            )
            if not validation.passed:
                bundle = self._repair_or_fallback_bundle(
                    job.id, bundle, validation.errors, evidence, plan
                )
                validation = validate_document_bundle(
                    bundle, plan=plan, evidence=evidence
                )
                self._update(
                    job.id,
                    {
                        "content_spec_json": bundle.model_dump(mode="json"),
                        "validation_results_json": validation.model_dump(mode="json"),
                    },
                )
            if not validation.passed:
                self._record_error(
                    job.id,
                    stage="validating",
                    code="artifact_seed_validation_failed",
                    message="; ".join(validation.errors[:8]),
                )
                raise RuntimeError(
                    "artifact seeded content validation failed: "
                    + "; ".join(validation.errors[:8])
                )

        job = self._update(
            job.id,
            {
                "status": "rendering",
                "stage": "rendering",
                "progress_pct": 80,
                "stage_progress": _progress(
                    "formats",
                    0,
                    len(job.requested_formats),
                    "Preparing requested files",
                ),
            },
        )
        with self._stage_timer(job.id, "rendering"):
            failures = self._render_formats(job, evidence, bundle)
        status = (
            "complete"
            if not failures
            else ("partial" if len(failures) < len(job.requested_formats) else "failed")
        )
        return self._update(
            job.id,
            {
                "status": status,
                "stage": status,
                "progress_pct": 100,
                "stage_progress": None,
                "error_code": "artifact_format_failures" if failures else None,
                "error_message_safe": f"Failed formats: {', '.join(failures)}"
                if failures
                else None,
                "completed_at": datetime.now(UTC),
            },
        )

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
        fallback_validation = validate_document_bundle(
            fallback, plan=plan, evidence=evidence
        )
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
