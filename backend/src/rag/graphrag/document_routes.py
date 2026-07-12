"""Document-scoped GraphRAG routes."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.dependencies import require_csrf, require_current_user
from ..auth.identity_models import UserRecord
from ..schemas.common import ErrorResponse
from ..schemas.docs import DocumentGraphEnrichmentResponse
from .document_enrichment_dependencies import (
    get_document_graph_enrichment_service,
)
from .document_enrichment_service import (
    DocumentGraphEnrichmentRejected,
    DocumentGraphEnrichmentResult,
    DocumentGraphEnrichmentService,
)

router = APIRouter(prefix="/docs", tags=["documents"])

_GRAPH_ENRICHMENT_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _graph_enrichment_result(
    action: Callable[[], DocumentGraphEnrichmentResult],
) -> DocumentGraphEnrichmentResult:
    try:
        return action()
    except DocumentGraphEnrichmentRejected as exc:
        raise HTTPException(
            status_code=_GRAPH_ENRICHMENT_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post(
    "/{document_id}/graph-enrichment",
    response_model=DocumentGraphEnrichmentResponse,
    responses={
        status.HTTP_202_ACCEPTED: {"model": DocumentGraphEnrichmentResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue optional graph enrichment for an indexed document",
)
async def queue_document_graph_enrichment(
    document_id: str,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentGraphEnrichmentService = Depends(
        get_document_graph_enrichment_service
    ),
) -> DocumentGraphEnrichmentResponse:
    require_csrf(request)
    result = _graph_enrichment_result(
        lambda: service.enqueue(document_id, actor=user)
    )
    return DocumentGraphEnrichmentResponse(
        document_id=result.document_id,
        job_id=result.job_id,
    )
