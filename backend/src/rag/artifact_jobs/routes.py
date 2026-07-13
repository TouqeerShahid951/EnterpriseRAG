"""Public HTTP routes for generated artifacts and artifact jobs."""

from datetime import UTC, datetime
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from ..auth.context import UserContext
from ..auth.dependencies import require_csrf, require_current_user
from ..auth.document_access import can_read_document
from ..auth.identity_models import UserRecord
from ..documents.models import DocumentRepository
from ..documents.repository import get_document_repository
from .dependencies import (
    get_artifact_job_repository,
    get_artifact_job_service,
    get_generated_artifact_repository,
    get_generated_artifact_storage,
)
from .generated_models import GeneratedArtifactRepository
from .job_models import ArtifactJobRepository
from .schemas import (
    ArtifactClarificationRequest,
    ArtifactJobDetail,
    ArtifactJobMutationResponse,
)
from .service import ArtifactJobActionError, ArtifactJobService
from .storage import GeneratedArtifactStorage


_job_router = APIRouter(prefix="/artifact-jobs", tags=["artifact-jobs"])
_download_router = APIRouter(prefix="/query", tags=["query"])
logger = logging.getLogger("rag.query.routes")


@_download_router.get(
    "/artifacts/{artifact_id}/content",
    summary="Download a generated query artifact",
)
async def get_generated_artifact_content(
    artifact_id: str,
    user: UserRecord = Depends(require_current_user),
    artifact_repo: GeneratedArtifactRepository = Depends(
        get_generated_artifact_repository
    ),
    artifact_job_repo: ArtifactJobRepository = Depends(get_artifact_job_repository),
    artifact_storage: GeneratedArtifactStorage = Depends(
        get_generated_artifact_storage
    ),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> StreamingResponse:
    artifact = artifact_repo.get_artifact(artifact_id)
    parent_job = (
        artifact_job_repo.get_job(artifact.job_id)
        if artifact and artifact.job_id
        else None
    )
    if (
        artifact is None
        or artifact.user_id != user.id
        or artifact.permission_version != user.permission_version
        or (
            artifact.expires_at is not None and artifact.expires_at <= datetime.now(UTC)
        )
        or (
            artifact.job_id is not None
            and (
                parent_job is None
                or parent_job.status not in {"complete", "partial"}
                or parent_job.cancellation_requested
                or (
                    parent_job.expires_at is not None
                    and parent_job.expires_at <= datetime.now(UTC)
                )
            )
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "artifact_not_found",
                "message": "Generated artifact was not found.",
            },
        )
    if any(
        (document := audit_repo.get_document(document_id)) is None
        or not can_read_document(user, document)
        for document_id in artifact.source_doc_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "artifact_not_found",
                "message": "Generated artifact was not found.",
            },
        )
    try:
        stored = artifact_storage.read(artifact.object_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "artifact_file_not_found",
                "message": "Generated artifact file was not found.",
            },
        ) from exc
    try:
        audit_repo.append_audit_event(
            event_type="query.artifact_downloaded",
            actor_id=user.id,
            target_type="generated_artifact",
            target_id=artifact.id,
            payload={
                "session_id": artifact.session_id,
                "trace_id": artifact.trace_id,
                "format": artifact.format,
                "filename": artifact.filename,
            },
        )
    except Exception:
        logger.error(
            "generated artifact download audit failed artifact_id=%s user_id=%s",
            artifact.id,
            user.id,
            exc_info=True,
        )
    filename = artifact.filename or stored.filename
    return StreamingResponse(
        iter([stored.content]),
        media_type=artifact.content_type or stored.content_type,
        headers={
            "Content-Disposition": _attachment_content_disposition(filename),
            "Content-Length": str(len(stored.content)),
        },
    )


@_job_router.get("/{job_id}", response_model=ArtifactJobDetail)
async def get_artifact_job(
    job_id: str,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobDetail:
    try:
        return service.get_for_user(job_id, _user_context(user))
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


@_job_router.post(
    "/{job_id}/clarifications", response_model=ArtifactJobMutationResponse
)
async def clarify_artifact_job(
    job_id: str,
    payload: ArtifactClarificationRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobMutationResponse:
    require_csrf(request)
    try:
        return ArtifactJobMutationResponse(
            job=service.add_clarifications(job_id, _user_context(user), payload.answers)
        )
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


@_job_router.post("/{job_id}/cancel", response_model=ArtifactJobMutationResponse)
async def cancel_artifact_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobMutationResponse:
    require_csrf(request)
    try:
        return ArtifactJobMutationResponse(
            job=service.cancel(job_id, _user_context(user))
        )
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


@_job_router.post("/{job_id}/retry", response_model=ArtifactJobMutationResponse)
async def retry_artifact_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobMutationResponse:
    require_csrf(request)
    try:
        return ArtifactJobMutationResponse(
            job=service.retry(job_id, _user_context(user))
        )
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


def _attachment_content_disposition(filename: str) -> str:
    safe_name = filename.replace('"', "'")
    encoded = quote(filename)
    return f"attachment; filename=\"{safe_name}\"; filename*=UTF-8''{encoded}"


def _user_context(user: UserRecord) -> UserContext:
    return UserContext(
        user_id=user.id,
        email=user.email,
        account_type=user.account_type,
        group_paths=user.group_paths,
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
    )


def _http_error(exc: ArtifactJobActionError) -> HTTPException:
    response_status = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "artifact_job_not_found"
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(
        status_code=response_status,
        detail={"code": exc.code, "message": exc.message},
    )


router = APIRouter()
router.include_router(_download_router)
router.include_router(_job_router)
