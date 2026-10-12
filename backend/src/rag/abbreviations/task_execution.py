"""Dedicated worker execution for glossary sources; it never invokes RAG indexing."""

from __future__ import annotations

import logging
from uuid import uuid4

from rag.ingestion.adapters.storage import UploadObjectReader
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.errors import WorkerStepError
from rag.ingestion.execution import build_backend_client
from rag.ingestion.config import WorkerConfig

from .source_import import extract_glossary_source


logger = logging.getLogger(__name__)


def run_glossary_source_import(
    payload: dict[str, object], *, run_token: str | None = None
) -> dict[str, object]:
    """Import one PDF/XLSX glossary source without chunks, vectors, or generations."""
    job = IngestJobPayload.from_dict(payload)
    config = WorkerConfig.from_env()
    backend = build_backend_client(config)
    token = str(run_token or "").strip() or str(uuid4())
    attempt = backend.start_attempt(
        job_id=job.job_id,
        run_token=token,
        delivery_id=job.delivery_id,
    )
    if not attempt.accepted:
        return {"job_id": job.job_id, "doc_id": job.doc_id, "status": attempt.job_status}
    try:
        backend.update_job(
            job_id=job.job_id,
            status="processing",
            progress_pct=10,
            stage_progress={"unit": "files", "current": 0, "total": 1, "label": "Reading glossary source"},
        )
        content = UploadObjectReader(config.minio).read(job.file_path)
        extracted = extract_glossary_source(
            content,
            content_type=job.content_type or "",
            filename=job.file_path,
        )
        if not extracted.entries:
            logger.warning(
                "Glossary source contains no usable entries job_id=%s doc_id=%s rejected_entries=%s",
                job.job_id,
                job.doc_id,
                list(extracted.rejected_entries),
            )
            raise WorkerStepError(
                "abbreviation_glossary_empty",
                "Glossary contains no usable abbreviation entries.",
            )
        backend.update_job(
            job_id=job.job_id,
            status="processing",
            progress_pct=70,
            stage_progress={"unit": "metadata", "current": len(extracted.entries), "total": len(extracted.entries), "label": "Validating glossary terms"},
            warnings=[f"Skipped {len(extracted.rejected_entries)} invalid glossary row(s)."]
            if extracted.rejected_entries
            else [],
        )
        backend.replace_abbreviation_glossary(
            document_id=job.doc_id,
            entries=list(extracted.entries),
        )
        backend.update_job(
            job_id=job.job_id,
            status="complete",
            progress_pct=100,
            stage_progress={"unit": "metadata", "current": len(extracted.entries), "total": len(extracted.entries), "label": "Glossary imported"},
        )
        return {"job_id": job.job_id, "doc_id": job.doc_id, "status": "complete", "entries_imported": len(extracted.entries)}
    except WorkerStepError as exc:
        backend.record_failure(
            job_id=job.job_id,
            error_code=exc.code,
            error_message_safe=exc.safe_message,
            retry_message=None,
        )
        raise
    except Exception as exc:
        backend.record_failure(
            job_id=job.job_id,
            error_code="glossary_import_failed",
            error_message_safe=str(exc)[:500],
            retry_message=None,
        )
        raise
