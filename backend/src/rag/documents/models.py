"""Document repository contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol

from ..audit.models import AuditEventRecord
from ..ingestion.job_models import IngestJobRecord as IngestJobRecord
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
    shared_group_paths: tuple[str, ...] = ()
    active_index_generation_id: str | None = None

    @property
    def owner_group_path(self) -> str:
        return self.group_path

    @property
    def access_group_paths(self) -> tuple[str, ...]:
        paths: list[str] = []
        seen: set[str] = set()
        for path in (self.group_path, *self.shared_group_paths):
            if path not in seen:
                seen.add(path)
                paths.append(path)
        return tuple(paths)

    @property
    def governance_owner(self) -> Literal["space", "system"]:
        return "system" if self.shared_group_paths else "space"


@dataclass(frozen=True)
class DocumentOverviewSpaceRecord:
    group_path: str
    library_documents: int
    current_versions: int
    processing_current: int
    review_current: int
    failed_current: int
    unknown_current: int


@dataclass(frozen=True)
class DocumentOverviewSnapshot:
    library_documents: int = 0
    current_versions: int = 0
    indexed_current: int = 0
    processing_current: int = 0
    review_current: int = 0
    failed_current: int = 0
    unknown_current: int = 0
    needs_attention: int = 0
    superseded_versions: int = 0
    expiring_soon_current: int = 0
    trash: int = 0
    attention_documents: tuple[DocumentRecord, ...] = ()
    spaces: tuple[DocumentOverviewSpaceRecord, ...] = ()


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
    def list_documents_by_ids(
        self, document_ids: tuple[str, ...]
    ) -> list[DocumentRecord]: ...
    def count_documents_by_owner_group(
        self,
        *,
        state: Literal["active", "deleted"] = "active",
        clearance_levels: tuple[ClearanceLevel, ...],
        group_paths: tuple[str, ...] | None,
    ) -> dict[str, int]: ...
    def summarize_document_overview(
        self,
        *,
        clearance_levels: tuple[ClearanceLevel, ...],
        group_paths: tuple[str, ...] | None,
        expiring_from: date,
        expiring_to: date,
        attention_limit: int,
    ) -> DocumentOverviewSnapshot: ...
    def get_document(self, document_id: str, *, include_deleted: bool = False) -> DocumentRecord | None: ...
    def replace_document_shares(
        self,
        document_id: str,
        *,
        group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None: ...
    def replace_document_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        shared_group_paths: list[str],
        actor_id: str | None,
    ) -> DocumentRecord | None: ...
    def update_document_clearance(self, document_id: str, clearance_level: ClearanceLevel) -> DocumentRecord | None: ...
    def update_document_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ) -> DocumentRecord | None: ...
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
    def replace_document_image_assets(
        self,
        *,
        doc_id: str,
        job_id: str,
        assets: list[dict[str, Any]],
    ) -> list[DocumentImageAssetRecord]: ...
    def list_document_image_assets(self, document_id: str) -> list[DocumentImageAssetRecord]: ...
    def get_document_image_asset(self, document_id: str, asset_id: str) -> DocumentImageAssetRecord | None: ...
