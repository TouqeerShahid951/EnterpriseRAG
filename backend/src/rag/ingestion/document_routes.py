"""Document-scoped ingestion routes."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.dependencies import require_csrf, require_current_user
from ..auth.identity_models import UserRecord
from ..documents.lifecycle.reingestion_dependencies import (
    get_document_reingestion_service,
)
from ..documents.lifecycle.reingestion_service import (
    DocumentReingestionRejected,
    DocumentReingestionResult,
    DocumentReingestionService,
)
from rag.shared.contracts.http import ErrorResponse
from rag.ingestion.schemas import DocumentReingestRequest, DocumentReingestResponse

router = APIRouter(prefix="/docs", tags=["documents"])

_REINGESTION_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _reingestion_result(
    action: Callable[[], DocumentReingestionResult],
) -> DocumentReingestionResult:
    try:
        return action()
    except DocumentReingestionRejected as exc:
        raise HTTPException(
            status_code=_REINGESTION_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post(
    "/{document_id}/reingest",
    response_model=DocumentReingestResponse,
    responses={
        status.HTTP_202_ACCEPTED: {"model": DocumentReingestResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reingest a document from its stored source file",
)
async def reingest_document(
    document_id: str,
    request: Request,
    payload: DocumentReingestRequest | None = None,
    user: UserRecord = Depends(require_current_user),
    service: DocumentReingestionService = Depends(
        get_document_reingestion_service
    ),
) -> DocumentReingestResponse:
    require_csrf(request)
    result = _reingestion_result(
        lambda: service.reingest(
            document_id,
            actor=user,
            retry_of_job_id=payload.retry_of_job_id if payload else None,
        )
    )
    return DocumentReingestResponse(
        document_id=result.document_id,
        job_id=result.job_id,
    )
