"""Visible progress reporting for durable artifact execution."""

from __future__ import annotations

import logging

from billiard.exceptions import SoftTimeLimitExceeded

from .execution_errors import (
    ArtifactJobCancelled,
    ArtifactJobLeaseLost,
    ArtifactPermissionChanged,
)


logger = logging.getLogger("rag.artifact_jobs")


class ArtifactExecutionProgress:
    """Map internal composition and rendering work onto persisted job progress."""

    def _record_composition_progress(
        self, job_id: str, *, current: int, total: int, phase: str
    ) -> None:
        bounded_total = max(total, 1)
        bounded_current = min(max(current, 0), bounded_total)
        if phase == "formatting":
            changes = {
                "status": "composing",
                "stage": "formatting_outputs",
                "progress_pct": 70,
                "stage_progress": _progress(
                    "slides", 0, 1, "Choosing title, sections, and slide layout"
                ),
            }
        else:
            if phase == "batch_complete":
                progress = 56 + int((bounded_current / bounded_total) * 14)
            else:
                progress = 56 + int(
                    ((max(bounded_current, 1) - 1) / bounded_total) * 14
                )
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
        except (
            ArtifactJobCancelled,
            ArtifactJobLeaseLost,
            ArtifactPermissionChanged,
            SoftTimeLimitExceeded,
        ):
            raise
        except Exception:
            logger.warning(
                "failed to record artifact composition progress job_id=%s phase=%s current=%s total=%s",
                job_id,
                phase,
                current,
                total,
                exc_info=True,
            )

    def _record_render_format_progress(
        self, job_id: str, artifact_format: str, current: int, total: int
    ) -> None:
        pct = 80 + int((max(current - 1, 0) / max(total, 1)) * 15)
        self._update(
            job_id,
            {
                "status": "rendering",
                "stage": f"rendering_{artifact_format}",
                "progress_pct": min(95, max(80, pct)),
                "stage_progress": _progress(
                    "formats",
                    current,
                    max(total, 1),
                    f"Rendering {artifact_format.upper()} ({current} of {max(total, 1)})",
                ),
            },
        )

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
        pct = int(
            format_start
            + (min(max(slide_current, 0), max(slide_total, 1)) / max(slide_total, 1))
            * format_span
        )
        self._update(
            job_id,
            {
                "status": "rendering",
                "stage": f"rendering_{artifact_format}_slide",
                "progress_pct": min(95, max(82, pct)),
                "stage_progress": _progress(
                    "slides",
                    slide_current,
                    max(slide_total, 1),
                    f"Building slide {slide_current} of {max(slide_total, 1)}: {label}",
                ),
            },
        )


def _progress(unit: str, current: int, total: int, label: str) -> dict[str, object]:
    return {
        "unit": unit,
        "current": max(0, current),
        "total": max(0, total),
        "label": label,
    }


def _format_complete_progress(current: int, total: int) -> int:
    return min(96, max(84, 80 + int((max(current, 1) / max(total, 1)) * 15)))
