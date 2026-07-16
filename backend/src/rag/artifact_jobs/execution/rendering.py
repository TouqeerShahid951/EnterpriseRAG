"""Deterministic rendering and publication for artifact jobs."""

from __future__ import annotations

from datetime import UTC, datetime
import logging

from billiard.exceptions import SoftTimeLimitExceeded

from rag.core.config import Settings
from rag.artifact_jobs.contracts import ArtifactContentBundle, EvidenceManifest
from rag.artifact_jobs.execution.errors import (
    ArtifactJobCancelled,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)
from rag.artifact_jobs.execution.progress import _format_complete_progress, _progress
from rag.artifact_jobs.job_models import ArtifactJobRecord
from rag.artifact_jobs.publisher import ArtifactPublisher
from rag.artifact_jobs.renderer import render_document


logger = logging.getLogger("rag.artifact_jobs")


class ArtifactFormatExecution:
    """Render requested formats independently and publish successful outputs."""

    config: Settings
    publisher: ArtifactPublisher
    _run_token: str | None

    def _render_formats(
        self,
        job: ArtifactJobRecord,
        evidence: EvidenceManifest,
        bundle: ArtifactContentBundle,
    ) -> list[str]:
        source_doc_ids = list(
            dict.fromkeys(record.doc_id for record in evidence.records)
        )
        return self._render_deterministic_formats(
            job, bundle, source_doc_ids, list(job.requested_formats)
        )

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
                self._record_render_format_progress(
                    job.id, artifact_format, index, total_formats
                )
                rendered = render_document(
                    artifact_format=artifact_format,  # type: ignore[arg-type]
                    bundle=bundle,
                    generated_at=datetime.now(UTC),
                    require_libreoffice=self.config.artifact_libreoffice_required,
                    progress_callback=(
                        lambda current, total, label, fmt=artifact_format, fmt_index=index, fmt_total=total_formats: (
                            self._record_slide_progress(
                                job.id, fmt, fmt_index, fmt_total, current, total, label
                            )
                        )
                    )
                    if artifact_format == "pptx"
                    else None,
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
            except (
                ArtifactJobCancelled,
                ArtifactJobLeaseLost,
                ArtifactPermissionChanged,
                SoftTimeLimitExceeded,
            ):
                raise
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
            self._update(
                job.id,
                {
                    "status": "rendering",
                    "stage": "storing",
                    "progress_pct": progress_pct,
                    "stage_progress": _progress(
                        "files", 0, 1, f"Saving {artifact_format.upper()} file"
                    ),
                },
            )
            self._check_cancelled(job.id)
            published = self.publisher.publish(
                job=job,
                filename=filename,
                artifact_format=artifact_format,
                content=content,
                content_type=content_type,
                source_doc_ids=source_doc_ids,
                smoke_warnings=warnings,
                expected_run_token=self._run_token,
                lease_guard=lambda: self._guard_publication(job, source_doc_ids),
            )
            publication_warnings = [
                item for item in published.warnings if item not in warnings
            ]
            if publication_warnings:
                self._record_error(
                    job.id,
                    stage="storing",
                    code="artifact_publish_warning",
                    message="; ".join(publication_warnings),
                    context={"format": artifact_format},
                )
            self._check_cancelled(job.id)

    def _record_format_error(
        self, job_id: str, artifact_format: str, exc: Exception
    ) -> None:
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
