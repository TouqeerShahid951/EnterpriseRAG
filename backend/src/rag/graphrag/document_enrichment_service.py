"""Application workflow for user-requested document graph enrichment."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from rag.shared.contracts.abbreviations import ABBREVIATION_GLOSSARY_DOC_TYPE

from ..auth.document_access import can_manage_document_ingestion, can_read_document
from ..auth.identity_models import UserRecord
from ..documents.models import DocumentRecord, DocumentRepository
from ..ingestion.job_models import IngestJobRepository
from .document_enrichment_ports import DocumentEnrichmentQueue


GraphEnrichmentErrorCategory = Literal[
    "not_found",
    "forbidden",
    "conflict",
    "unavailable",
]


class DocumentGraphEnrichmentRejected(RuntimeError):
    def __init__(
        self,
        *,
        category: GraphEnrichmentErrorCategory,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DocumentGraphEnrichmentResult:
    document_id: str
    job_id: str


class DocumentGraphEnrichmentService:
    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        job_repo: IngestJobRepository,
        queue: DocumentEnrichmentQueue,
        enrichment_enabled: Callable[[], bool],
    ) -> None:
        self._document_repo = document_repo
        self._job_repo = job_repo
        self._queue = queue
        self._enrichment_enabled = enrichment_enabled

    def enqueue(
        self,
        document_id: str,
        *,
        actor: UserRecord,
    ) -> DocumentGraphEnrichmentResult:
        document = self._managed_document(document_id, actor)
        if document.doc_type == ABBREVIATION_GLOSSARY_DOC_TYPE:
            raise DocumentGraphEnrichmentRejected(
                category="conflict",
                code="document_not_graph_eligible",
                message="Abbreviation glossaries use structured query expansion instead of graph enrichment.",
            )
        if not self._enrichment_enabled():
            raise DocumentGraphEnrichmentRejected(
                category="conflict",
                code="graphrag_disabled",
                message="Graph enrichment is disabled for this workspace.",
            )
        job = self._job_repo.get_latest_ingest_job_for_document(
            document.id,
            statuses=frozenset({"complete"}),
        )
        if document.ingest_status != "complete" or job is None:
            raise DocumentGraphEnrichmentRejected(
                category="conflict",
                code="document_not_indexed",
                message=(
                    "Graph enrichment is available after document indexing "
                    "completes."
                ),
            )
        try:
            self._queue.enqueue(
                document_id=document.id,
                job_id=job.id,
                reason="user_request",
                index_generation_id=document.active_index_generation_id,
            )
        except Exception as exc:  # noqa: BLE001 - queue adapters vary
            self._document_repo.append_audit_event(
                event_type="documents.graph_enrichment.enqueue_failed",
                actor_id=actor.id,
                target_type="document",
                target_id=document.id,
                payload={"job_id": job.id, "error": str(exc)[:300]},
            )
            raise DocumentGraphEnrichmentRejected(
                category="unavailable",
                code="graphrag_enqueue_failed",
                message="Graph enrichment could not be queued.",
            ) from exc
        self._document_repo.append_audit_event(
            event_type="documents.graph_enrichment.queued",
            actor_id=actor.id,
            target_type="document",
            target_id=document.id,
            payload={"job_id": job.id, "reason": "user_request"},
        )
        return DocumentGraphEnrichmentResult(
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
            raise DocumentGraphEnrichmentRejected(
                category="not_found",
                code="document_not_found",
                message="Document was not found.",
            )
        if not can_manage_document_ingestion(actor, document):
            raise DocumentGraphEnrichmentRejected(
                category="forbidden",
                code="document_ingestion_forbidden",
                message=(
                    "Only the uploader or a scoped admin can manage this "
                    "ingestion job."
                ),
            )
        return document
