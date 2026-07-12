"""Application workflow for reingesting a stored document source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..auth.document_access import can_manage_document_ingestion, can_read_document
from ..auth.identity_models import UserRecord
from ..ingestion.contracts import IngestJobPayload
from ..ingestion.job_models import IngestJobRepository
from ..ingestion.queue import IngestQueue
from .models import DocumentRecord, DocumentRepository
from .storage import UploadStorage


ReingestionErrorCategory = Literal[
    "not_found",
    "forbidden",
    "conflict",
    "unavailable",
]


class DocumentReingestionRejected(RuntimeError):
    def __init__(
        self,
        *,
        category: ReingestionErrorCategory,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DocumentReingestionResult:
    document_id: str
    job_id: str


class DocumentReingestionService:
    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        job_repo: IngestJobRepository,
        storage: UploadStorage,
        queue: IngestQueue,
    ) -> None:
        self._document_repo = document_repo
        self._job_repo = job_repo
        self._storage = storage
        self._queue = queue

    def reingest(
        self,
        document_id: str,
        *,
        actor: UserRecord,
        retry_of_job_id: str | None,
    ) -> DocumentReingestionResult:
        document = self._managed_document(document_id, actor)
        retry_id = self._validated_retry_job(document, retry_of_job_id)
        if self._job_repo.get_latest_ingest_job_for_document(
            document.id,
            statuses=frozenset(
                {"scheduled", "queued", "processing", "human_review"}
            ),
        ):
            raise DocumentReingestionRejected(
                category="conflict",
                code="document_ingest_active",
                message="Document already has an active ingestion job.",
            )
        stored = self._read_source(document)
        job = self._job_repo.create_ingest_job(
            doc_id=document.id,
            status="queued",
            progress_pct=0,
            origin="reingest",
            retry_of_job_id=retry_id,
        )
        message = _ingest_message_for_document(
            document,
            job.id,
            stored,
            self._document_repo,
        )
        try:
            self._queue.enqueue(message)
        except RuntimeError as exc:
            self._job_repo.update_ingest_job(
                job.id,
                status="failed",
                progress_pct=0,
                error_code="queue_unavailable",
                error_message_safe=str(exc),
            )
            self._audit(
                document,
                actor_id=actor.id,
                job_id=job.id,
                retry_of_job_id=retry_id,
                action_result="failed",
                error_code="queue_unavailable",
            )
            raise DocumentReingestionRejected(
                category="unavailable",
                code="queue_unavailable",
                message="Ingestion queue is unavailable.",
            ) from exc
        self._audit(
            document,
            actor_id=actor.id,
            job_id=job.id,
            retry_of_job_id=retry_id,
            action_result="success",
        )
        return DocumentReingestionResult(
            document_id=document.id,
            job_id=job.id,
        )

    def _managed_document(
        self,
        document_id: str,
        actor: UserRecord,
    ) -> DocumentRecord:
        document = self._document_repo.get_document(document_id)
        if document is None or not can_read_document(actor, document):
            raise DocumentReingestionRejected(
                category="not_found",
                code="document_not_found",
                message="Document was not found.",
            )
        if not can_manage_document_ingestion(actor, document):
            raise DocumentReingestionRejected(
                category="forbidden",
                code="document_ingestion_forbidden",
                message=(
                    "Only the uploader or a scoped admin can manage this "
                    "ingestion job."
                ),
            )
        return document

    def _validated_retry_job(
        self,
        document: DocumentRecord,
        retry_of_job_id: str | None,
    ) -> str | None:
        if not retry_of_job_id:
            return None
        retry_job = self._job_repo.get_ingest_job(retry_of_job_id)
        if retry_job is None or retry_job.doc_id != document.id:
            raise DocumentReingestionRejected(
                category="not_found",
                code="retry_job_not_found",
                message=(
                    "The ingestion job being retried was not found for this "
                    "document."
                ),
            )
        if retry_job.status not in {"failed", "cancelled"}:
            raise DocumentReingestionRejected(
                category="conflict",
                code="retry_job_not_retryable",
                message=(
                    "Only failed or cancelled ingestion jobs can be linked as "
                    "retries."
                ),
            )
        return retry_job.id

    def _read_source(self, document: DocumentRecord) -> object:
        if not document.file_path:
            raise DocumentReingestionRejected(
                category="conflict",
                code="document_source_missing",
                message="Document does not have a stored source file.",
            )
        try:
            return self._storage.read(document.file_path)
        except RuntimeError as exc:
            raise DocumentReingestionRejected(
                category="conflict",
                code="document_source_missing",
                message="Document source file was not found.",
            ) from exc

    def _audit(
        self,
        document: DocumentRecord,
        *,
        actor_id: str,
        job_id: str,
        retry_of_job_id: str | None,
        action_result: str,
        error_code: str | None = None,
    ) -> None:
        payload = {
            "group_path": document.group_path,
            "clearance_level": document.clearance_level,
            "job_id": job_id,
            "retry_of_job_id": retry_of_job_id,
            "action_result": action_result,
        }
        if error_code is not None:
            payload["error_code"] = error_code
        self._document_repo.append_audit_event(
            event_type="documents.reingest",
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload=payload,
        )


def _ingest_message_for_document(
    document: DocumentRecord,
    job_id: str,
    stored: object,
    repo: DocumentRepository,
) -> IngestJobPayload:
    filename = str(
        getattr(stored, "filename", "") or _filename_for_document(document)
    )
    content_type = getattr(
        stored,
        "content_type",
        None,
    ) or _content_type_for_filename(filename)
    supersedes = repo.list_superseded_document_ids(document.id) or list(
        document.pending_supersedes
    )
    return IngestJobPayload(
        job_id=job_id,
        doc_id=document.id,
        file_path=str(document.file_path),
        group_path=document.group_path,
        acl_group_paths=list(document.access_group_paths),
        clearance_level=document.clearance_level,
        doc_type=document.doc_type,
        effective_date=(
            document.effective_date.isoformat()
            if document.effective_date
            else None
        ),
        supersedes=supersedes,
        expiry_date=(
            document.expiry_date.isoformat() if document.expiry_date else None
        ),
        description=document.description,
        content_type=str(content_type) if content_type else None,
    )


def _filename_for_document(document: DocumentRecord) -> str:
    if document.title and Path(document.title).suffix:
        return document.title
    if document.file_path:
        return Path(document.file_path).name
    return f"{document.id}.bin"


def _content_type_for_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".docx"):
        return (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".json"):
        return "application/json"
    return "application/octet-stream"
