"""Service-token-protected artifact worker context validation."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..artifact_jobs.repository import ArtifactJobRepository, get_artifact_job_repository
from ..auth.document_access import can_read_document
from ..repositories.documents import DocumentRepository, get_document_repository
from ..repositories.identity import IdentityRepository, get_identity_repository
from ..schemas.internal import ServiceTokenContext
from .service_token_auth import require_service_token


router = APIRouter(tags=["internal-artifact-jobs"])


@router.get("/artifact-jobs/{job_id}/context")
async def artifact_job_context(
    job_id: str,
    jobs: ArtifactJobRepository = Depends(get_artifact_job_repository),
    identities: IdentityRepository = Depends(get_identity_repository),
    documents: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> dict[str, object]:
    _ = service
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "artifact_job_not_found", "message": "Artifact job was not found."})
    user = identities.get_user_by_id(job.user_id)
    if user is None or not user.is_active or user.permission_version != job.permission_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "artifact_authorization_changed", "message": "Artifact job authorization is no longer valid."},
        )
    for document_id in job.document_ids:
        document = documents.get_document(document_id)
        if document is None or not can_read_document(user, document):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "artifact_document_access_changed", "message": "Artifact job document access is no longer valid."},
            )
    return {
        "job_id": job.id,
        "user_id": job.user_id,
        "permission_version": job.permission_version,
        "group_paths": list(job.group_paths),
        "group_path": job.group_path,
        "document_ids": list(job.document_ids),
        "original_request": job.original_request,
        "requested_formats": list(job.requested_formats),
    }
