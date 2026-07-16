"""Application service for restore and document deletion workflows."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Literal
from uuid import uuid4

from rag.auth.document_access import can_read_document, can_write_document
from rag.auth.identity_models import UserRecord
from rag.auth.permissions import can_manage_group_path, is_global_admin
from rag.ingestion.contracts import IngestJobPayload
from rag.ingestion.delivery.service import (
    IngestDeliveryService,
    dispatch_pending_deliveries,
)
from rag.ingestion.job_models import IngestJobRecord, IngestJobRepository
from rag.ingestion.queue import IngestQueue
from rag.documents.access_scope.ports import (
    DocumentGraphCleanupError,
    DocumentGraphCleanupResult,
)
from rag.documents.lifecycle.ports import (
    DocumentGraphCleanup,
    DocumentImageDeletionStore,
    DocumentVectorIndex,
    DocumentVectorIndexError,
    GraphPartitionRebuildQueue,
)
from rag.documents.models import DocumentRecord, DocumentRepository
from rag.documents.storage import StoredUploadContent, UploadStorage


logger = logging.getLogger(__name__)

LifecycleErrorCategory = Literal[
    "not_found",
    "forbidden",
    "conflict",
    "unavailable",
    "bad_gateway",
]

ACTIVE_INGEST_STATUSES = frozenset(
    {"scheduled", "queued", "processing", "human_review"}
)


class DocumentLifecycleRejected(RuntimeError):
    """A safe lifecycle rejection that an HTTP route can map to a response."""

    def __init__(
        self,
        *,
        category: LifecycleErrorCategory,
        code: str,
        message: str,
    ) -> None:
        self.category = category
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class RestoreDocumentCommand:
    document_id: str
    actor: UserRecord


@dataclass(frozen=True)
class DeleteDocumentCommand:
    document_id: str
    actor: UserRecord


@dataclass(frozen=True)
class RestoreDocumentResult:
    document_id: str
    job_id: str


@dataclass(frozen=True)
class DeleteDocumentResult:
    document_id: str
    status: Literal["soft_deleted", "permanently_deleted"]


class DocumentLifecycleService:
    """Coordinate document state changes with required external cleanup."""

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: IngestJobRepository,
        storage: UploadStorage,
        image_storage: DocumentImageDeletionStore,
        ingest_queue: IngestQueue,
        vectors: DocumentVectorIndex,
        graph_cleanup: DocumentGraphCleanup,
        graph_queue: GraphPartitionRebuildQueue,
        graphrag_enabled: bool,
        qdrant_collection: str,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._delivery = IngestDeliveryService(jobs)
        self._storage = storage
        self._image_storage = image_storage
        self._ingest_queue = ingest_queue
        self._vectors = vectors
        self._graph_cleanup = graph_cleanup
        self._graph_queue = graph_queue
        self._graphrag_enabled = graphrag_enabled
        self._qdrant_collection = qdrant_collection

    def restore(self, command: RestoreDocumentCommand) -> RestoreDocumentResult:
        document = self._require_writable(
            command.actor,
            self._documents.get_document(command.document_id, include_deleted=True),
        )
        if document.deleted_at is None:
            raise DocumentLifecycleRejected(
                category="conflict",
                code="document_not_deleted",
                message="Document is not in Trash.",
            )
        if self._jobs.get_latest_ingest_job_for_document(
            document.id,
            statuses=ACTIVE_INGEST_STATUSES,
        ):
            raise DocumentLifecycleRejected(
                category="conflict",
                code="document_ingest_active",
                message="Document already has an active ingestion job.",
            )
        source = self._read_source(document)
        restored = self._documents.restore_document(document.id)
        if restored is None:
            raise self._not_found()
        job = self._queue_restore(restored, source=source, actor_id=command.actor.id)
        return RestoreDocumentResult(document_id=restored.id, job_id=job.id)

    def soft_delete(self, command: DeleteDocumentCommand) -> DeleteDocumentResult:
        document = self._require_writable(
            command.actor,
            self._documents.get_document(command.document_id),
        )
        graph_cleanup = self._delete_graph(
            document,
            event_type="documents.delete",
            actor_id=command.actor.id,
        )
        try:
            self._vectors.delete_document_points(document.id)
        except DocumentVectorIndexError as exc:
            self._documents.append_audit_event(
                event_type="documents.delete",
                actor_id=command.actor.id,
                target_type="document",
                target_id=document.id,
                payload={
                    "group_path": document.group_path,
                    "action_result": "failed",
                    "error_code": "document_vectors_delete_failed",
                },
            )
            raise DocumentLifecycleRejected(
                category="bad_gateway",
                code="document_vectors_delete_failed",
                message=f"Unable to delete indexed document vectors: {exc}",
            ) from exc
        deleted = self._documents.soft_delete_document(document.id)
        if deleted is None:
            raise self._not_found()
        rebuild_status = self._enqueue_partition_rebuild(
            document,
            event_type="documents.delete",
            actor_id=command.actor.id,
            partition_key=graph_cleanup.partition_key,
        )
        self._documents.append_audit_event(
            event_type="documents.delete",
            actor_id=command.actor.id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "action_result": "success",
                "qdrant_collection": self._qdrant_collection,
                "graphrag_cleanup_status": graph_cleanup.status,
                "graphrag_partition_key": graph_cleanup.partition_key,
                "graphrag_rebuild_status": rebuild_status,
            },
        )
        return DeleteDocumentResult(document_id=document.id, status="soft_deleted")

    def permanently_delete(
        self,
        command: DeleteDocumentCommand,
    ) -> DeleteDocumentResult:
        document = self._require_visible(
            command.actor,
            self._documents.get_document(command.document_id, include_deleted=True),
        )
        if not self._can_permanently_delete(command.actor, document):
            raise DocumentLifecycleRejected(
                category="forbidden",
                code="document_forbidden",
                message=(
                    "Only platform admins and scoped Space Admins can permanently "
                    "delete documents."
                ),
            )
        graph_cleanup = self._delete_graph(
            document,
            event_type="documents.permanent_delete",
            actor_id=command.actor.id,
        )
        try:
            self._vectors.delete_document_points(document.id)
            for asset in self._documents.list_document_image_assets(document.id):
                self._image_storage.delete(asset.object_path)
            if document.file_path:
                self._storage.delete(document.file_path)
        except DocumentVectorIndexError as exc:
            raise DocumentLifecycleRejected(
                category="bad_gateway",
                code="document_vectors_delete_failed",
                message=f"Unable to delete indexed document vectors: {exc}",
            ) from exc
        except RuntimeError as exc:
            raise DocumentLifecycleRejected(
                category="bad_gateway",
                code="document_file_delete_failed",
                message=f"Unable to delete uploaded document file: {exc}",
            ) from exc
        deleted = self._documents.permanently_delete_document(document.id)
        if deleted is None:
            raise self._not_found()
        rebuild_status = self._enqueue_partition_rebuild(
            document,
            event_type="documents.permanent_delete",
            actor_id=command.actor.id,
            partition_key=graph_cleanup.partition_key,
        )
        self._documents.append_audit_event(
            event_type="documents.permanent_delete",
            actor_id=command.actor.id,
            target_type="document",
            target_id=document.id,
            payload={
                "file_path": document.file_path,
                "group_path": document.group_path,
                "qdrant_collection": self._qdrant_collection,
                "action_result": "success",
                "graphrag_cleanup_status": graph_cleanup.status,
                "graphrag_partition_key": graph_cleanup.partition_key,
                "graphrag_rebuild_status": rebuild_status,
            },
        )
        return DeleteDocumentResult(
            document_id=document.id,
            status="permanently_deleted",
        )

    def _queue_restore(
        self,
        document: DocumentRecord,
        *,
        source: StoredUploadContent,
        actor_id: str,
    ) -> IngestJobRecord:
        job_id = str(uuid4())
        message = self._ingest_message(document, job_id, source)
        mutation = self._delivery.create_queued_job(
            message,
            origin="restore",
            event_kind="restore",
        )
        job = mutation.job
        if job is None or not mutation.changed:
            raise RuntimeError("unable to create queued restore delivery")
        self._documents.append_audit_event(
            event_type="documents.restore",
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "clearance_level": document.clearance_level,
                "job_id": job.id,
                "retry_of_job_id": None,
                "action_result": "success",
            },
        )
        self._dispatch_best_effort(job.id)
        return job

    def _dispatch_best_effort(self, job_id: str) -> None:
        try:
            dispatch_pending_deliveries(
                self._delivery,
                self._ingest_queue,
                limit=1,
            )
        except Exception:
            logger.warning(
                "ingestion delivery deferred job_id=%s event_kind=restore",
                job_id,
            )

    def _read_source(self, document: DocumentRecord) -> StoredUploadContent:
        if not document.file_path:
            raise DocumentLifecycleRejected(
                category="conflict",
                code="document_source_missing",
                message="Document does not have a stored source file.",
            )
        try:
            return self._storage.read(document.file_path)
        except RuntimeError as exc:
            raise DocumentLifecycleRejected(
                category="conflict",
                code="document_source_missing",
                message="Document source file was not found.",
            ) from exc

    def _ingest_message(
        self,
        document: DocumentRecord,
        job_id: str,
        source: StoredUploadContent,
    ) -> IngestJobPayload:
        filename = source.filename or _filename_for(document)
        content_type = source.content_type or _content_type_for(filename)
        supersedes = self._documents.list_superseded_document_ids(
            document.id
        ) or list(document.pending_supersedes)
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

    def _delete_graph(
        self,
        document: DocumentRecord,
        *,
        event_type: str,
        actor_id: str,
    ) -> DocumentGraphCleanupResult:
        partition_key = self._graph_cleanup.partition_key_for(document)
        try:
            return self._graph_cleanup.delete_document(
                document_id=document.id,
                partition_key=partition_key,
            )
        except DocumentGraphCleanupError as exc:
            self._documents.append_audit_event(
                event_type=event_type,
                actor_id=actor_id,
                target_type="document",
                target_id=document.id,
                payload={
                    "group_path": document.group_path,
                    "action_result": "failed",
                    "error_code": "document_graphrag_delete_failed",
                    "graphrag_partition_key": partition_key,
                },
            )
            raise DocumentLifecycleRejected(
                category="bad_gateway",
                code="document_graphrag_delete_failed",
                message=f"Unable to delete GraphRAG document data: {exc}",
            ) from exc

    def _enqueue_partition_rebuild(
        self,
        document: DocumentRecord,
        *,
        event_type: str,
        actor_id: str,
        partition_key: str | None,
    ) -> str:
        if not self._graphrag_enabled:
            return "skipped"
        if not partition_key:
            return "skipped_missing_partition"
        try:
            self._graph_queue.enqueue_partition_rebuild(
                document_id=document.id,
                partition_key=partition_key,
                reason=event_type,
            )
        except RuntimeError as exc:
            self._documents.append_audit_event(
                event_type=event_type,
                actor_id=actor_id,
                target_type="document",
                target_id=document.id,
                payload={
                    "group_path": document.group_path,
                    "action_result": "warning",
                    "warning_code": "graphrag_rebuild_enqueue_failed",
                    "graphrag_partition_key": partition_key,
                    "message": str(exc)[:240],
                },
            )
            return "enqueue_failed"
        return "queued"

    @staticmethod
    def _can_permanently_delete(
        actor: UserRecord,
        document: DocumentRecord,
    ) -> bool:
        if document.shared_group_paths:
            return is_global_admin(actor)
        return can_manage_group_path(actor, document.group_path)

    @staticmethod
    def _require_visible(
        actor: UserRecord,
        document: DocumentRecord | None,
    ) -> DocumentRecord:
        if document is None or not can_read_document(actor, document):
            raise DocumentLifecycleService._not_found()
        return document

    @classmethod
    def _require_writable(
        cls,
        actor: UserRecord,
        document: DocumentRecord | None,
    ) -> DocumentRecord:
        visible = cls._require_visible(actor, document)
        if not can_write_document(actor, visible):
            raise DocumentLifecycleRejected(
                category="forbidden",
                code="document_forbidden",
                message="User cannot modify this document.",
            )
        return visible

    @staticmethod
    def _not_found() -> DocumentLifecycleRejected:
        return DocumentLifecycleRejected(
            category="not_found",
            code="document_not_found",
            message="Document was not found.",
        )


def _content_type_for(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".docx"):
        return (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


def _filename_for(document: DocumentRecord) -> str:
    if document.title and Path(document.title).suffix:
        return document.title
    if document.file_path:
        return Path(document.file_path).name
    return f"{document.id}.bin"
