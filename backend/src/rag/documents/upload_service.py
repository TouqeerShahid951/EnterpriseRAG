"""Application service for accepting and queueing one document upload."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from uuid import uuid4

from ..auth.abac import normalize_group_path
from ..auth.document_access import can_write_document
from ..auth.permissions import (
    can_manage_group_path,
    can_upload_to_group,
    is_global_admin,
)
from ..ingestion.contracts import IngestJobPayload
from ..ingestion.quality import normalize_ingestion_quality_preset
from ..ingestion.queue import IngestQueue
from ..repositories.document_models import DocumentRepository
from ..auth.identity_models import IdentityRepository, UserRecord
from ..ingestion.job_models import IngestJobRepository
from ..shared.contracts.clearance import clearance_rank, normalize_clearance_level
from .scanning import FileScanner
from .storage import UploadStorage
from .upload_validation import (
    UploadRejected,
    default_filename,
    default_title,
    scan_upload,
    validated_description,
    validated_document_type,
    validate_declared_dates,
    validate_upload_size,
)


@dataclass(frozen=True)
class UploadDocumentCommand:
    actor: UserRecord
    content: bytes
    filename: str | None
    declared_content_type: str | None
    group_path: str
    clearance_level: str
    effective_date: date | None
    expiry_date: date | None
    doc_type: str | None
    description: str | None
    quality_preset: str | None
    supersedes: tuple[str, ...]
    shared_group_paths: tuple[str, ...]


@dataclass(frozen=True)
class UploadDocumentResult:
    job_id: str


class UploadDocument:
    """Validate, persist, audit, and dispatch a document upload."""

    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        document_repo: DocumentRepository,
        job_repo: IngestJobRepository,
        storage: UploadStorage,
        scanner: FileScanner,
        queue: IngestQueue,
        max_upload_bytes: int,
    ) -> None:
        self._identity_repo = identity_repo
        self._document_repo = document_repo
        self._job_repo = job_repo
        self._storage = storage
        self._scanner = scanner
        self._queue = queue
        self._max_upload_bytes = max_upload_bytes

    def execute(self, command: UploadDocumentCommand) -> UploadDocumentResult:
        normalized_group = self._validated_upload_group(
            command.group_path, command.actor
        )
        normalized_shared_groups = self._validated_upload_shares(
            command.shared_group_paths,
            owner_group_path=normalized_group,
            user=command.actor,
        )
        normalized_clearance = _validated_upload_clearance(
            command.clearance_level, command.actor
        )
        validate_declared_dates(command.effective_date, command.expiry_date)
        normalized_description = validated_description(command.description)
        normalized_quality_preset = _validated_quality_preset(command.quality_preset)
        supersedes_ids = self._validate_supersedes(command.supersedes, command.actor)
        initial_doc_type = _normalize_declared_doc_type(command.doc_type)
        validate_upload_size(command.content, max_bytes=self._max_upload_bytes)
        content_type = validated_document_type(
            command.content,
            command.filename,
            command.declared_content_type,
        )
        content_hash = hashlib.sha256(command.content).hexdigest()
        if self._document_repo.find_current_by_content_hash(content_hash):
            raise UploadRejected(
                category="conflict",
                code="duplicate_document",
                message="A current document with the same content already exists.",
            )
        scan_upload(self._scanner, command.content)
        stored = self._storage.put(
            filename=command.filename or default_filename(content_type),
            content=command.content,
            content_type=content_type,
        )
        document = self._document_repo.create_document(
            title=command.filename or default_title(content_type),
            source_id=_upload_source_id(content_hash),
            group_path=normalized_group,
            clearance_level=normalized_clearance,
            doc_type=initial_doc_type,
            effective_date=command.effective_date,
            expiry_date=command.expiry_date,
            description=normalized_description,
            uploaded_by=command.actor.id,
            file_path=stored.object_path,
            content_hash=content_hash,
            pending_supersedes=supersedes_ids,
            ingest_status="queued",
        )
        if normalized_shared_groups:
            shared_document = self._document_repo.replace_document_shares(
                document.id,
                group_paths=normalized_shared_groups,
                actor_id=command.actor.id,
            )
            if shared_document is not None:
                document = shared_document
        job = self._job_repo.create_ingest_job(
            doc_id=document.id,
            status="queued",
            progress_pct=0,
            origin="upload",
        )
        self._audit_upload(
            actor=command.actor,
            doc_id=document.id,
            job_id=job.id,
            filename=command.filename,
            size=stored.size_bytes,
            group=normalized_group,
            shared_groups=normalized_shared_groups,
            clearance=normalized_clearance,
            content_type=content_type,
            quality_preset=normalized_quality_preset,
        )
        self._enqueue_upload(
            job_id=job.id,
            doc_id=document.id,
            file_path=stored.object_path,
            group_path=normalized_group,
            acl_group_paths=list(document.access_group_paths),
            clearance_level=normalized_clearance,
            doc_type=initial_doc_type,
            effective_date=command.effective_date,
            expiry_date=command.expiry_date,
            description=normalized_description,
            supersedes=supersedes_ids,
            content_type=content_type,
            quality_preset=normalized_quality_preset,
        )
        return UploadDocumentResult(job_id=job.id)

    def _validated_upload_group(self, group_path: str, user: UserRecord) -> str:
        normalized = normalize_group_path(group_path)
        known = {group.path for group in self._identity_repo.list_groups()}
        if normalized not in known:
            raise UploadRejected(
                category="invalid",
                code="group_not_found",
                message="Upload group does not exist.",
            )
        if not can_upload_to_group(user, normalized):
            raise UploadRejected(
                category="forbidden",
                code="upload_group_forbidden",
                message="User cannot upload into this group.",
            )
        return normalized

    def _validated_upload_shares(
        self,
        group_paths: tuple[str, ...],
        *,
        owner_group_path: str,
        user: UserRecord,
    ) -> list[str]:
        if not group_paths:
            return []
        known = {group.path for group in self._identity_repo.list_groups()}
        shared: list[str] = []
        seen: set[str] = set()
        for raw_path in group_paths:
            group_path = normalize_group_path(raw_path)
            if group_path == owner_group_path or group_path in seen:
                continue
            if group_path not in known:
                raise UploadRejected(
                    category="invalid",
                    code="group_not_found",
                    message=f"Shared Knowledge Space does not exist: {group_path}",
                )
            seen.add(group_path)
            shared.append(group_path)
        if not shared:
            return []
        if is_global_admin(user):
            return shared
        if (
            user.account_type == "space_admin"
            and can_manage_group_path(user, owner_group_path)
            and all(can_manage_group_path(user, group_path) for group_path in shared)
        ):
            return shared
        raise UploadRejected(
            category="forbidden",
            code="upload_share_forbidden",
            message="User cannot share uploads with one or more selected Knowledge Spaces.",
        )

    def _validate_supersedes(
        self, doc_ids: tuple[str, ...], user: UserRecord
    ) -> list[str]:
        validated: list[str] = []
        for doc_id in doc_ids:
            document = self._document_repo.get_document(doc_id)
            if document is None:
                raise UploadRejected(
                    category="invalid",
                    code="invalid_supersedes",
                    message=f"Superseded document does not exist: {doc_id}",
                )
            if not can_write_document(user, document):
                raise UploadRejected(
                    category="forbidden",
                    code="supersedes_forbidden",
                    message="User cannot supersede one or more documents.",
                )
            validated.append(document.id)
        return validated

    def _audit_upload(
        self,
        *,
        actor: UserRecord,
        doc_id: str,
        job_id: str,
        filename: str | None,
        size: int,
        group: str,
        shared_groups: list[str],
        clearance: str,
        content_type: str,
        quality_preset: str | None,
    ) -> None:
        payload: dict[str, object] = {
            "job_id": job_id,
            "filename": filename,
            "size_bytes": size,
            "group_path": group,
            "clearance_level": clearance,
            "content_type": content_type,
        }
        if shared_groups:
            payload["shared_group_paths"] = shared_groups
        if quality_preset:
            payload["quality_preset"] = quality_preset
        self._document_repo.append_audit_event(
            event_type="upload.queued",
            actor_id=actor.id,
            target_type="document",
            target_id=doc_id,
            payload=payload,
        )

    def _enqueue_upload(
        self,
        *,
        job_id: str,
        doc_id: str,
        file_path: str,
        group_path: str,
        acl_group_paths: list[str],
        clearance_level: str,
        doc_type: str | None,
        effective_date: date | None,
        expiry_date: date | None,
        description: str | None,
        supersedes: list[str],
        content_type: str,
        quality_preset: str | None,
    ) -> None:
        try:
            self._queue.enqueue(
                IngestJobPayload(
                    job_id=job_id,
                    doc_id=doc_id,
                    file_path=file_path,
                    group_path=group_path,
                    acl_group_paths=acl_group_paths,
                    clearance_level=clearance_level,
                    doc_type=doc_type,
                    effective_date=effective_date.isoformat()
                    if effective_date
                    else None,
                    supersedes=supersedes,
                    expiry_date=expiry_date.isoformat() if expiry_date else None,
                    description=description,
                    content_type=content_type,
                    quality_preset=quality_preset,
                )
            )
        except RuntimeError as exc:
            self._job_repo.update_ingest_job(
                job_id,
                status="failed",
                progress_pct=0,
                error_code="queue_unavailable",
                error_message_safe=str(exc),
            )
            raise UploadRejected(
                category="unavailable",
                code="queue_unavailable",
                message="Upload queue is unavailable.",
            ) from exc


def _validated_upload_clearance(clearance_level: str, user: UserRecord) -> str:
    try:
        normalized = normalize_clearance_level(clearance_level)
    except ValueError as exc:
        raise UploadRejected(
            category="invalid",
            code="invalid_clearance_level",
            message=str(exc),
        ) from exc
    if clearance_rank(normalized) > clearance_rank(user.clearance_level):
        raise UploadRejected(
            category="forbidden",
            code="upload_clearance_forbidden",
            message="User cannot upload above their clearance level.",
        )
    return normalized


def _validated_quality_preset(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = normalize_ingestion_quality_preset(value)
    if normalized != value.strip().lower():
        raise UploadRejected(
            category="invalid",
            code="invalid_quality_preset",
            message="Ingestion quality preset must be fast, balanced, or high_accuracy.",
        )
    return normalized


def _normalize_declared_doc_type(value: str | None) -> str | None:
    normalized = " ".join((value or "").strip().lower().split())
    return normalized[:80] or None


def _upload_source_id(content_hash: str) -> str:
    return f"upload:{content_hash}:{uuid4()}"


__all__ = [
    "UploadDocument",
    "UploadDocumentCommand",
    "UploadDocumentResult",
    "UploadRejected",
]
