"""Document repository contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol

from ..shared.contracts.clearance import ClearanceLevel


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    title: str | None
    source_id: str
    group_path: str
    clearance_level: ClearanceLevel
    doc_type: str | None
    language: str | None
    effective_date: date | None
    expiry_date: date | None
    description: str | None
    summary: str | None
    topics: tuple[str, ...]
    llm_topics: tuple[str, ...]
    auto_doc_type: str | None
    extracted_dates: dict[str, Any]
    metadata_flags: dict[str, Any]
    is_current: bool
    superseded_by: str | None
    pending_supersedes: tuple[str, ...]
    content_hash: str | None
    uploaded_by: str | None
    file_path: str | None
    ingest_status: str
    deleted_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class DocumentEntityRecord:
    doc_id: str
    text: str
    type: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class DocumentCrossReferenceRecord:
    doc_id: str
    ref_text: str
    ref_type: str
    position: int | None = None


@dataclass(frozen=True)
class IngestJobRecord:
    id: str
    doc_id: str
    origin: str
    status: str
    progress_pct: int
    stage_progress: dict[str, Any] | None
    attempt_count: int
    last_heartbeat_at: datetime | None
    warnings: tuple[str, ...]
    parser_provenance: dict[str, Any] | None
    error_code: str | None
    error_message_safe: str | None
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class AuditEventRecord:
    id: str
    event_type: str
    actor_id: str | None
    target_type: str | None
    target_id: str | None
    payload: dict[str, Any]
    created_at: datetime | None


@dataclass(frozen=True)
class ReviewBatchRecord:
    id: str
    job_id: str
    doc_id: str
    status: str
    parsed_items: list[dict[str, Any]]
    resume_payload: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ReviewItemRecord:
    id: str
    batch_id: str
    doc_id: str
    doc_title: str
    item_index: int
    item_type: str
    page_start: int | None
    page_end: int | None
    bbox: list[float] | None
    quality_flags: tuple[str, ...]
    partial_text: str
    corrected_text: str | None
    confidence: float | None
    status: str
    assigned_to: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ReviewDecisionRecord:
    item: ReviewItemRecord
    batch: ReviewBatchRecord
    batch_complete: bool = False


@dataclass(frozen=True)
class DocumentImageAssetRecord:
    id: str
    doc_id: str
    job_id: str | None
    source_kind: str
    page: int | None
    bbox: list[float] | None
    object_path: str
    content_type: str
    width: int | None
    height: int | None
    content_hash: str
    extracted_text: str | None
    caption: str | None
    confidence: float | None
    quality_flags: tuple[str, ...]
    created_at: datetime | None


class DocumentRepository(Protocol):
    def create_document(self, **kwargs: Any) -> DocumentRecord: ...
    def list_documents(self, *, state: Literal["active", "deleted"] = "active") -> list[DocumentRecord]: ...
    def get_document(self, document_id: str, *, include_deleted: bool = False) -> DocumentRecord | None: ...
    def save_document_metadata(
        self,
        *,
        document_id: str,
        summary: str | None,
        language: str | None,
        topics: list[str],
        llm_topics: list[str],
        doc_type: str | None = None,
        auto_doc_type: str | None,
        extracted_dates: dict[str, Any],
        metadata_flags: dict[str, Any],
        entities: list[DocumentEntityRecord],
        cross_references: list[DocumentCrossReferenceRecord],
    ) -> DocumentRecord | None: ...
    def list_document_entities(self, document_id: str) -> list[DocumentEntityRecord]: ...
    def list_document_cross_references(self, document_id: str) -> list[DocumentCrossReferenceRecord]: ...
    def find_current_by_content_hash(self, content_hash: str) -> DocumentRecord | None: ...
    def soft_delete_document(self, document_id: str) -> DocumentRecord | None: ...
    def restore_document(self, document_id: str) -> DocumentRecord | None: ...
    def permanently_delete_document(self, document_id: str) -> DocumentRecord | None: ...
    def create_ingest_job(
        self,
        *,
        doc_id: str,
        status: str,
        progress_pct: int,
        origin: str = "unknown",
    ) -> IngestJobRecord: ...
    def get_ingest_job(self, job_id: str) -> IngestJobRecord | None: ...
    def list_ingest_jobs(self) -> list[IngestJobRecord]: ...
    def get_active_ingest_job_for_document(self, doc_id: str) -> IngestJobRecord | None: ...
    def update_ingest_job(
        self,
        job_id: str,
        *,
        status: str,
        progress_pct: int,
        stage_progress: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        error_code: str | None = None,
        error_message_safe: str | None = None,
    ) -> IngestJobRecord | None: ...
    def requeue_stale_ingest_job(
        self,
        job_id: str,
        *,
        stale_before: datetime,
        max_attempts: int,
    ) -> IngestJobRecord | None: ...
    def start_ingest_attempt(
        self,
        job_id: str,
        *,
        max_attempts: int,
        stale_after_seconds: int = 120,
    ) -> IngestJobRecord | None: ...
    def heartbeat_ingest_job(self, job_id: str) -> IngestJobRecord | None: ...
    def record_ingest_parser_provenance(self, job_id: str, *, provenance: dict[str, Any]) -> IngestJobRecord | None: ...
    def mark_superseded(self, *, new_doc_id: str, old_doc_ids: list[str]) -> list[DocumentRecord]: ...
    def list_version_chain(self, document_id: str) -> list[DocumentRecord]: ...
    def list_superseded_document_ids(self, document_id: str) -> list[str]: ...
    def append_audit_event(
        self,
        *,
        event_type: str,
        actor_id: str | None,
        target_type: str | None,
        target_id: str | None,
        payload: dict[str, Any],
    ) -> None: ...
    def list_audit_events(self, *, limit: int = 100) -> list[AuditEventRecord]: ...
    def create_review_batch(
        self,
        *,
        job_id: str,
        doc_id: str,
        parsed_items: list[dict[str, Any]],
        resume_payload: dict[str, Any],
        review_items: list[dict[str, Any]],
    ) -> ReviewBatchRecord: ...
    def get_review_batch(self, batch_id: str) -> ReviewBatchRecord | None: ...
    def list_review_items(self, *, status: str = "pending") -> list[ReviewItemRecord]: ...
    def list_review_items_for_batch(self, batch_id: str) -> list[ReviewItemRecord]: ...
    def approve_review_item(self, item_id: str, *, corrected_text: str, reviewer_id: str) -> ReviewDecisionRecord | None: ...
    def reject_review_item(self, item_id: str, *, reviewer_id: str) -> ReviewDecisionRecord | None: ...
    def replace_document_image_assets(
        self,
        *,
        doc_id: str,
        job_id: str,
        assets: list[dict[str, Any]],
    ) -> list[DocumentImageAssetRecord]: ...
    def list_document_image_assets(self, document_id: str) -> list[DocumentImageAssetRecord]: ...
    def get_document_image_asset(self, document_id: str, asset_id: str) -> DocumentImageAssetRecord | None: ...
