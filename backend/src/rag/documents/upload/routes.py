"""Document upload and upload-status routes."""

from __future__ import annotations

from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from rag.auth.dependencies import require_csrf, require_current_user
from rag.auth.document_access import can_read_document
from rag.core.config import settings
from rag.ingestion.queue import IngestQueue, get_ingest_queue
from rag.documents.repository import DocumentRepository, get_document_repository
from rag.ingestion.job_dependencies import get_ingest_job_repository
from rag.ingestion.job_models import IngestJobRepository
from rag.auth.identity_models import IdentityRepository, UserRecord
from rag.auth.identity_repository import get_identity_repository
from rag.shared.contracts.http import StubResponse
from rag.shared.contracts.clearance import DEFAULT_CLEARANCE_LEVEL
from rag.documents.dependencies import get_file_scanner, get_upload_storage
from rag.documents.scanning import FileScanner
from rag.documents.storage import UploadStorage
from rag.documents.upload.schemas import JobStatusResponse, UploadResponse
from rag.documents.upload.service import (
    UploadDocument,
    UploadDocumentCommand,
    UploadRejected,
)
from rag.documents.upload.status import build_job_status_response

router = APIRouter(prefix="/upload", tags=["upload"])

_UPLOAD_STATUS_BY_CATEGORY = {
    "invalid": status.HTTP_400_BAD_REQUEST,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "too_large": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
}


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
    shared_group_paths: list[str] = Form(default_factory=list),
    user: UserRecord = Depends(require_current_user),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    scanner: FileScanner = Depends(get_file_scanner),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> UploadResponse:
    require_csrf(request)
    content = await file.read()
    service = UploadDocument(
        identity_repo=identity_repo,
        document_repo=document_repo,
        job_repo=job_repo,
        storage=storage,
        scanner=scanner,
        queue=queue,
        max_upload_bytes=settings.upload_max_bytes,
    )
    try:
        result = service.execute(
            UploadDocumentCommand(
                actor=user,
                content=content,
                filename=file.filename,
                declared_content_type=file.content_type,
                group_path=group_path,
                clearance_level=clearance_level,
                effective_date=effective_date,
                expiry_date=expiry_date,
                doc_type=doc_type,
                description=description,
                quality_preset=quality_preset,
                supersedes=tuple(supersedes),
                shared_group_paths=tuple(shared_group_paths),
            )
        )
    except UploadRejected as exc:
        raise HTTPException(
            status_code=_UPLOAD_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return UploadResponse(job_id=result.job_id)


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
    user: UserRecord = Depends(require_current_user),
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
) -> JobStatusResponse:
    job = job_repo.get_ingest_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Upload job was not found."},
        )
    document = document_repo.get_document(job.doc_id, include_deleted=True)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "document_not_found",
                "message": "Uploaded document was not found.",
            },
        )
    if not can_read_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "upload_status_forbidden",
                "message": "User cannot view this upload job.",
            },
        )
    return build_job_status_response(job)
