"""Document upload and upload-status routes."""

from __future__ import annotations

from datetime import date
import hashlib
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_csrf, require_current_user
from ...auth.document_access import can_write_document
from ...auth.permissions import can_upload_to_group
from ...repositories.documents import DocumentRepository, get_document_repository
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...schemas.common import StubResponse
from ...schemas.upload import JobStatusResponse, UploadResponse
from ...shared.contracts.clearance import DEFAULT_CLEARANCE_LEVEL, clearance_rank, normalize_clearance_level
from ...shared.ingestion_quality import normalize_ingestion_quality_preset
from ...services.document_uploads import (
    default_filename,
    default_title,
    scan_upload,
    validated_description,
    validated_document_type,
    validate_declared_dates,
    validate_upload_size,
)
from ...services.file_scanning import FileScanner, get_file_scanner
from ...services.ingest_queue import IngestQueue, IngestQueueMessage, get_ingest_queue
from ...services.upload_status import build_job_status_response
from ...services.upload_storage import UploadStorage, get_upload_storage

router = APIRouter(prefix="/upload", tags=["upload"])

@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadResponse,
    responses={
        status.HTTP_202_ACCEPTED: {"model": UploadResponse},
        status.HTTP_501_NOT_IMPLEMENTED: {"model": StubResponse},
    },
    summary="Queue a document upload for ingestion",
)
async def create_upload(
    request: Request,
    file: UploadFile = File(...),
    group_path: str = Form(...),
    clearance_level: str = Form(default=DEFAULT_CLEARANCE_LEVEL),
    effective_date: date | None = Form(default=None),
    expiry_date: date | None = Form(default=None),
    doc_type: str | None = Form(default=None),
    description: str | None = Form(default=None),
    quality_preset: str | None = Form(default=None),
    supersedes: list[str] = Form(default_factory=list),
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    document_repo: DocumentRepository = Depends(get_document_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    scanner: FileScanner = Depends(get_file_scanner),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> UploadResponse:
    require_csrf(request)
    normalized_group = _validated_upload_group(group_path, user, identity_repo)
    normalized_clearance = _validated_upload_clearance(clearance_level, user)
    validate_declared_dates(effective_date, expiry_date)
    normalized_description = validated_description(description)
    normalized_quality_preset = _validated_quality_preset(quality_preset)
    supersedes_ids = _validate_supersedes(list(supersedes), user, document_repo)
    initial_doc_type = _normalize_declared_doc_type(doc_type)
    content = await file.read()
    validate_upload_size(content)
    content_type = validated_document_type(content, file.filename, file.content_type)
    content_hash = hashlib.sha256(content).hexdigest()
    if document_repo.find_current_by_content_hash(content_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "duplicate_document", "message": "A current document with the same content already exists."},
        )
    scan_upload(scanner, content)
    stored = storage.put(filename=file.filename or default_filename(content_type), content=content, content_type=content_type)
    document = document_repo.create_document(
        title=file.filename or default_title(content_type),
        source_id=_upload_source_id(content_hash),
        group_path=normalized_group,
        clearance_level=normalized_clearance,
        doc_type=initial_doc_type,
        effective_date=effective_date,
        expiry_date=expiry_date,
        description=normalized_description,
        uploaded_by=user.id,
        file_path=stored.object_path,
        content_hash=content_hash,
        pending_supersedes=supersedes_ids,
        ingest_status="queued",
    )
    job = document_repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin="upload")
    _audit_upload(document_repo, user, document.id, job.id, file.filename, stored.size_bytes, normalized_group, normalized_clearance, content_type, normalized_quality_preset)
    _enqueue_upload(queue, document_repo, job.id, document.id, stored.object_path, normalized_group, normalized_clearance, initial_doc_type, effective_date, expiry_date, normalized_description, supersedes_ids, content_type, normalized_quality_preset)
    return UploadResponse(job_id=job.id)


@router.get(
    "/{job_id}/status",
    responses={
        status.HTTP_200_OK: {"model": JobStatusResponse},
        status.HTTP_501_NOT_IMPLEMENTED: {"model": StubResponse},
    },
    summary="Read upload job status",
)
async def get_upload_status(
    job_id: str,
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> JobStatusResponse:
    job = document_repo.get_ingest_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Upload job was not found."},
        )
    return build_job_status_response(job)


def _validated_upload_group(group_path: str, user: UserRecord, repo: IdentityRepository) -> str:
    normalized = normalize_group_path(group_path)
    known = {group.path for group in repo.list_groups()}
    if normalized not in known:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "group_not_found", "message": "Upload group does not exist."},
        )
    if not can_upload_to_group(user, normalized):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "upload_group_forbidden", "message": "User cannot upload into this group."},
        )
    return normalized


def _validated_upload_clearance(clearance_level: str, user: UserRecord) -> str:
    try:
        normalized = normalize_clearance_level(clearance_level)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_clearance_level", "message": str(exc)},
        ) from exc
    if clearance_rank(normalized) > clearance_rank(user.clearance_level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "upload_clearance_forbidden", "message": "User cannot upload above their clearance level."},
        )
    return normalized


def _upload_source_id(content_hash: str) -> str:
    return f"upload:{content_hash}:{uuid4()}"


def _normalize_declared_doc_type(value: str | None) -> str | None:
    normalized = " ".join((value or "").strip().lower().split())
    return normalized[:80] or None


def _validate_supersedes(doc_ids: list[str], user: UserRecord, repo: DocumentRepository) -> list[str]:
    validated: list[str] = []
    for doc_id in doc_ids:
        document = repo.get_document(doc_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_supersedes", "message": f"Superseded document does not exist: {doc_id}"},
            )
        if not can_write_document(user, document):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "supersedes_forbidden", "message": "User cannot supersede one or more documents."},
            )
        validated.append(document.id)
    return validated


def _validated_quality_preset(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = normalize_ingestion_quality_preset(value)
    if normalized != value.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_quality_preset", "message": "Ingestion quality preset must be fast, balanced, or high_accuracy."},
        )
    return normalized


def _audit_upload(repo: DocumentRepository, user: UserRecord, doc_id: str, job_id: str, filename: str | None, size: int, group: str, clearance: str, content_type: str, quality_preset: str | None) -> None:
    payload = {"job_id": job_id, "filename": filename, "size_bytes": size, "group_path": group, "clearance_level": clearance, "content_type": content_type}
    if quality_preset:
        payload["quality_preset"] = quality_preset
    repo.append_audit_event(
        event_type="upload.queued",
        actor_id=user.id,
        target_type="document",
        target_id=doc_id,
        payload=payload,
    )


def _enqueue_upload(
    queue: IngestQueue,
    repo: DocumentRepository,
    job_id: str,
    doc_id: str,
    file_path: str,
    group_path: str,
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
        queue.enqueue(
            IngestQueueMessage(
                job_id=job_id,
                doc_id=doc_id,
                file_path=file_path,
                group_path=group_path,
                acl_group_paths=[group_path],
                clearance_level=clearance_level,
                doc_type=doc_type,
                effective_date=effective_date.isoformat() if effective_date else None,
                supersedes=supersedes,
                expiry_date=expiry_date.isoformat() if expiry_date else None,
                description=description,
                content_type=content_type,
                quality_preset=quality_preset,
            )
        )
    except RuntimeError as exc:
        repo.update_ingest_job(job_id, status="failed", progress_pct=0, error_code="queue_unavailable", error_message_safe=str(exc))
        raise HTTPException(status_code=503, detail={"code": "queue_unavailable", "message": "Upload queue is unavailable."}) from exc
