"""Public lifecycle APIs for asynchronous artifact jobs."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...auth.context import UserContext
from ...auth.dependencies import require_csrf, require_current_user
from ...repositories.identity_models import UserRecord
from ...schemas.artifact_jobs import (
    ArtifactClarificationRequest,
    ArtifactJobDetail,
    ArtifactJobMutationResponse,
)
from ...artifact_jobs.service import (
    ArtifactJobActionError,
    ArtifactJobService,
    get_artifact_job_service,
)


router = APIRouter(prefix="/artifact-jobs", tags=["artifact-jobs"])


@router.get("/{job_id}", response_model=ArtifactJobDetail)
async def get_artifact_job(
    job_id: str,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobDetail:
    try:
        return service.get_for_user(job_id, _user_context(user))
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


@router.post("/{job_id}/clarifications", response_model=ArtifactJobMutationResponse)
async def clarify_artifact_job(
    job_id: str,
    payload: ArtifactClarificationRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobMutationResponse:
    require_csrf(request)
    try:
        return ArtifactJobMutationResponse(job=service.add_clarifications(job_id, _user_context(user), payload.answers))
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


@router.post("/{job_id}/cancel", response_model=ArtifactJobMutationResponse)
async def cancel_artifact_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobMutationResponse:
    require_csrf(request)
    try:
        return ArtifactJobMutationResponse(job=service.cancel(job_id, _user_context(user)))
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


@router.post("/{job_id}/retry", response_model=ArtifactJobMutationResponse)
async def retry_artifact_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: ArtifactJobService = Depends(get_artifact_job_service),
) -> ArtifactJobMutationResponse:
    require_csrf(request)
    try:
        return ArtifactJobMutationResponse(job=service.retry(job_id, _user_context(user)))
    except ArtifactJobActionError as exc:
        raise _http_error(exc) from exc


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
    response_status = status.HTTP_404_NOT_FOUND if exc.code == "artifact_job_not_found" else status.HTTP_409_CONFLICT
    return HTTPException(status_code=response_status, detail={"code": exc.code, "message": exc.message})
