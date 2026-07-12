from __future__ import annotations

import base64
import json

from rag.api.routes.ingest_job_routes import _graphrag_queued_task_from_redis_item
from rag.repositories.ingest_job_models import IngestJobRecord
from rag.documents.upload_status import build_job_status_response


def test_docling_progress_promotes_public_stage_and_step() -> None:
    response = build_job_status_response(
        _job(
            progress_pct=34,
            stage_progress={
                "unit": "pages",
                "current": 8,
                "total": 40,
                "label": "Docling OCR repairing selected pages 9-12 of 40 (PDF pages 120-123)",
            },
        )
    )

    assert response.stage == "docling_repair"
    assert response.stage_label == "Docling repair"
    assert response.stage_detail.startswith("Docling OCR repairing")
    assert _step_state(response.steps, "docling_repair") == "active"


def test_vision_progress_promotes_public_stage_and_step() -> None:
    response = build_job_status_response(
        _job(
            progress_pct=34,
            stage_progress={
                "unit": "pages",
                "current": 1,
                "total": 3,
                "label": "Vision layout repairing page 2 of 3 (PDF page 7)",
            },
        )
    )

    assert response.stage == "vision_layout_repair"
    assert response.stage_label == "Vision repair"
    assert response.stage_detail == "Vision layout repairing page 2 of 3 (PDF page 7)"
    assert _step_state(response.steps, "vision_layout_repair") == "active"


def test_image_progress_promotes_public_stage_and_step() -> None:
    response = build_job_status_response(
        _job(
            progress_pct=35,
            stage_progress={
                "unit": "images",
                "current": 3,
                "total": 12,
                "label": "Image analysis analyzing page image 4 of 12 (PDF page 74)",
            },
        )
    )

    assert response.stage == "image_analysis"
    assert response.stage_label == "Image analysis"
    assert response.stage_detail.startswith("Image analysis analyzing")
    assert _step_state(response.steps, "image_analysis") == "active"


def test_metadata_progress_promotes_metadata_enrichment() -> None:
    response = build_job_status_response(
        _job(
            progress_pct=37,
            stage_progress={
                "unit": "metadata",
                "current": 1,
                "total": 13,
                "label": "Waiting on metadata model slow-metadata-model for 15s",
            },
        )
    )

    assert response.stage == "metadata_enrichment"
    assert response.stage_label == "Metadata enrichment"
    assert response.stage_detail == "Waiting on metadata model slow-metadata-model for 15s"
    assert _step_state(response.steps, "metadata_enrichment") == "active"


def test_failed_status_keeps_terminal_copy_and_failed_work_step() -> None:
    response = build_job_status_response(
        _job(
            status="failed",
            progress_pct=34,
            stage_progress={
                "unit": "pages",
                "current": 1,
                "total": 3,
                "label": "Vision layout repairing page 2 of 3 (PDF page 7)",
            },
            error_message_safe="Vision model timed out.",
        )
    )

    assert response.stage == "failed"
    assert response.stage_label == "Upload failed"
    assert response.stage_detail == "Vision model timed out."
    assert response.stage_progress is not None
    assert _step_state(response.steps, "vision_layout_repair") == "failed"


def test_graphrag_queue_preview_decodes_celery_task_payload() -> None:
    body = base64.b64encode(json.dumps([[{"job_id": "job-1", "doc_id": "doc-1"}], {}, {}]).encode("utf-8")).decode("ascii")
    raw_message = json.dumps({
        "headers": {"id": "task-1", "task": "apps.ingestion.tasks.index_document_graphrag"},
        "body": body,
    }).encode("utf-8")

    task = _graphrag_queued_task_from_redis_item(raw_message)

    assert task is not None
    assert task.task_id == "task-1"
    assert task.task_name == "apps.ingestion.tasks.index_document_graphrag"
    assert task.job_id == "job-1"
    assert task.document_id == "doc-1"


def _job(
    *,
    status: str = "processing",
    progress_pct: int = 0,
    stage_progress: dict[str, object] | None = None,
    error_message_safe: str | None = None,
) -> IngestJobRecord:
    return IngestJobRecord(
        id="job-1",
        doc_id="doc-1",
        retry_of_job_id=None,
        origin="upload",
        status=status,
        progress_pct=progress_pct,
        stage_progress=stage_progress,
        attempt_count=1,
        last_heartbeat_at=None,
        run_token=None,
        warnings=(),
        parser_provenance=None,
        error_code=None,
        error_message_safe=error_message_safe,
        created_at=None,
        updated_at=None,
        completed_at=None,
    )


def _step_state(steps, step_id: str) -> str:
    for step in steps:
        if step.id == step_id:
            return step.state
    raise AssertionError(f"missing step {step_id}")
