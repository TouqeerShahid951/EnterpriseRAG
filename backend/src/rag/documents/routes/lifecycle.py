"""Document restore and deletion HTTP routes."""

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...auth.dependencies import require_csrf, require_current_user
from ...auth.identity_models import UserRecord
from ...schemas.common import ErrorResponse
from ...schemas.docs import DeleteDocumentResponse, DocumentReingestResponse
from ..lifecycle_dependencies import get_document_lifecycle_service
from ..lifecycle_service import (
    DeleteDocumentCommand,
    DocumentLifecycleRejected,
    DocumentLifecycleService,
    RestoreDocumentCommand,
)

router = APIRouter(prefix="/docs")

LifecycleResult = TypeVar("LifecycleResult")

_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "bad_gateway": status.HTTP_502_BAD_GATEWAY,
}


def _lifecycle_result(action: Callable[[], LifecycleResult]) -> LifecycleResult:
    try:
        return action()
    except DocumentLifecycleRejected as exc:
        raise HTTPException(
            status_code=_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post(
    "/{document_id}/restore",
    response_model=DocumentReingestResponse,
    responses={
        status.HTTP_202_ACCEPTED: {"model": DocumentReingestResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
    summary="Restore a soft-deleted document and queue reingestion",
)
async def restore_document(
    document_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
) -> DocumentReingestResponse:
    require_csrf(request)
    result = _lifecycle_result(
        lambda: service.restore(
            RestoreDocumentCommand(document_id=document_id, actor=user)
        )
    )
    return DocumentReingestResponse(
        document_id=result.document_id,
        job_id=result.job_id,
    )


@router.delete(
    "/{document_id}",
    responses={
        status.HTTP_200_OK: {"model": DeleteDocumentResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Soft delete a document",
)
async def delete_document(
    document_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
) -> DeleteDocumentResponse:
    require_csrf(request)
    result = _lifecycle_result(
        lambda: service.soft_delete(
            DeleteDocumentCommand(document_id=document_id, actor=user)
        )
    )
    return DeleteDocumentResponse(id=result.document_id, status=result.status)


@router.delete(
    "/{document_id}/permanent",
    responses={
        status.HTTP_200_OK: {"model": DeleteDocumentResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
    summary="Permanently delete a document and its indexed assets",
)
async def permanently_delete_document(
    document_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentLifecycleService = Depends(get_document_lifecycle_service),
) -> DeleteDocumentResponse:
    require_csrf(request)
    result = _lifecycle_result(
        lambda: service.permanently_delete(
            DeleteDocumentCommand(document_id=document_id, actor=user)
        )
    )
    return DeleteDocumentResponse(id=result.document_id, status=result.status)
