"""Retire legacy database connector sync schedules and indexed snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..documents.models import DocumentRepository
from ..ingestion.folder_schedule_models import FolderScheduleRecord, FolderScheduleRepository


class _VectorStore(Protocol):
    def delete_document_points(self, doc_id: str) -> None: ...


class _ObjectStorage(Protocol):
    def delete(self, object_path: str) -> None: ...


@dataclass(frozen=True)
class ConnectorScheduleRetirementResult:
    schedules_deleted: int
    documents_deleted: int
    vectors_deleted: int
    files_deleted: int
    skipped_documents: int


def retire_connector_schedules(
    *,
    schedule_repo: FolderScheduleRepository,
    document_repo: DocumentRepository,
    qdrant: _VectorStore | None = None,
    storage: _ObjectStorage | None = None,
    image_storage: _ObjectStorage | None = None,
    actor_id: str | None = None,
) -> ConnectorScheduleRetirementResult:
    schedules = [schedule for schedule in schedule_repo.list_schedules() if schedule.source_type == "connector"]
    document_schedule_ids = _connector_document_schedule_ids(schedule_repo, schedules)
    documents_deleted = 0
    vectors_deleted = 0
    files_deleted = 0
    skipped_documents = 0

    for document_id, schedule_ids in sorted(document_schedule_ids.items()):
        document = document_repo.get_document(document_id, include_deleted=True)
        if document is None:
            skipped_documents += 1
            continue
        if not _is_document_from_connector_schedule(document.source_id, schedule_ids):
            skipped_documents += 1
            continue
        if qdrant is not None:
            qdrant.delete_document_points(document.id)
            vectors_deleted += 1
        if image_storage is not None:
            for asset in document_repo.list_document_image_assets(document.id):
                image_storage.delete(asset.object_path)
                files_deleted += 1
        if storage is not None and document.file_path:
            storage.delete(document.file_path)
            files_deleted += 1
        if document_repo.permanently_delete_document(document.id) is not None:
            documents_deleted += 1

    schedules_deleted = 0
    for schedule in schedules:
        if schedule_repo.delete_schedule(schedule.id) is not None:
            schedules_deleted += 1

    if schedules_deleted or documents_deleted:
        document_repo.append_audit_event(
            event_type="connector.schedules_retired",
            actor_id=actor_id,
            target_type="folder_schedule",
            target_id=None,
            payload={
                "source_type": "connector",
                "schedules_deleted": schedules_deleted,
                "documents_deleted": documents_deleted,
                "vectors_deleted": vectors_deleted,
                "files_deleted": files_deleted,
                "skipped_documents": skipped_documents,
            },
        )

    return ConnectorScheduleRetirementResult(
        schedules_deleted=schedules_deleted,
        documents_deleted=documents_deleted,
        vectors_deleted=vectors_deleted,
        files_deleted=files_deleted,
        skipped_documents=skipped_documents,
    )


def _connector_document_schedule_ids(
    schedule_repo: FolderScheduleRepository,
    schedules: list[FolderScheduleRecord],
) -> dict[str, set[str]]:
    document_schedule_ids: dict[str, set[str]] = {}
    for schedule in schedules:
        for run in schedule_repo.list_runs(schedule.id):
            for item in schedule_repo.list_run_items(run.id):
                if item.document_id:
                    document_schedule_ids.setdefault(item.document_id, set()).add(schedule.id)
    return document_schedule_ids


def _is_document_from_connector_schedule(source_id: str, schedule_ids: set[str]) -> bool:
    return any(source_id.startswith(f"connector:{schedule_id}:") for schedule_id in schedule_ids)
