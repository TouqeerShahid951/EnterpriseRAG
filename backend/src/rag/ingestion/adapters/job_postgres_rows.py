"""PostgreSQL ingestion-job row mapping helpers."""

from __future__ import annotations

from typing import Any

from ..job_models import IngestJobRecord, IngestJobView


def _job_view_from_row(row: dict[str, Any]) -> IngestJobView:
    job = _job_from_row(row)
    return IngestJobView(
        job=job,
        document_title=str(row.get("document_title") or job.doc_id),
        group_path=str(row["group_path"]),
        clearance_level=str(row["clearance_level"]),
        uploaded_by=str(row["uploaded_by"]) if row.get("uploaded_by") else None,
    )


def _job_from_row(row: dict[str, Any]) -> IngestJobRecord:
    return IngestJobRecord(
        id=str(row["id"]),
        doc_id=str(row["doc_id"]),
        retry_of_job_id=str(row["retry_of_job_id"])
        if row.get("retry_of_job_id")
        else None,
        origin=str(row.get("origin") or "unknown"),
        status=str(row["status"]),
        progress_pct=int(row["progress_pct"]),
        stage_progress=_json_object(row.get("stage_progress"))
        if row.get("stage_progress") is not None
        else None,
        attempt_count=int(row.get("attempt_count") or 0),
        last_heartbeat_at=row.get("last_heartbeat_at"),
        run_token=str(row["run_token"]) if row.get("run_token") else None,
        warnings=tuple(str(value) for value in _json_list(row.get("warnings"))),
        parser_provenance=(
            _json_object(row.get("parser_provenance"))
            if row.get("parser_provenance") is not None
            else None
        ),
        error_code=row.get("error_code"),
        error_message_safe=row.get("error_message_safe"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        completed_at=row.get("completed_at"),
    )


def _require_row(row: dict[str, Any] | None, operation: str) -> dict[str, Any]:
    if row is None:
        raise RuntimeError(f"{operation} unexpectedly returned no row")
    return row

def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
