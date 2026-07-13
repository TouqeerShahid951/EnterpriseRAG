"""Document metadata and supersession HTTP routes."""

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...auth.dependencies import require_csrf, require_current_user
from ...auth.identity_models import UserRecord
from ...schemas.common import ErrorResponse
from ...schemas.docs import (
    Document,
    DocumentClearanceUpdateRequest,
    DocumentTopicsUpdateRequest,
    SupersedeRequest,
    VersionChainResponse,
)
from ..metadata_dependencies import get_document_metadata_service
from ..metadata_service import DocumentMetadataRejected, DocumentMetadataService
from .presenters import document_to_schema, version_node

router = APIRouter(prefix="/docs")

MetadataResult = TypeVar("MetadataResult")

_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "bad_request": status.HTTP_400_BAD_REQUEST,
    "upstream": status.HTTP_502_BAD_GATEWAY,
}


def _metadata_result(action: Callable[[], MetadataResult]) -> MetadataResult:
    try:
        return action()
    except DocumentMetadataRejected as exc:
        raise HTTPException(
            status_code=_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.patch(
    "/{document_id}/clearance",
    response_model=Document,
    responses={
        status.HTTP_200_OK: {"model": Document},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
    summary="Update document clearance",
)
async def update_document_clearance(
    document_id: str,
    payload: DocumentClearanceUpdateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentMetadataService = Depends(get_document_metadata_service),
) -> Document:
    require_csrf(request)
    updated = _metadata_result(
        lambda: service.update_clearance(
            document_id,
            clearance_level=payload.clearance_level,
            actor=user,
        )
    )
    return document_to_schema(updated)


@router.patch(
    "/{document_id}/topics",
    response_model=Document,
    responses={
        status.HTTP_200_OK: {"model": Document},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
    summary="Update document topics",
)
async def update_document_topics(
    document_id: str,
    payload: DocumentTopicsUpdateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentMetadataService = Depends(get_document_metadata_service),
) -> Document:
    require_csrf(request)
    updated = _metadata_result(
        lambda: service.update_topics(
            document_id,
            topics=payload.topics,
            llm_topics=payload.llm_topics,
            actor=user,
        )
    )
    return document_to_schema(updated)


@router.post(
    "/{document_id}/supersede",
    response_model=VersionChainResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Mark older documents as superseded by this document",
)
async def supersede_documents(
    document_id: str,
    payload: SupersedeRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentMetadataService = Depends(get_document_metadata_service),
) -> VersionChainResponse:
    require_csrf(request)
    chain = _metadata_result(
        lambda: service.supersede(
            document_id,
            superseded_document_ids=payload.supersedes,
            actor=user,
        )
    )
    return VersionChainResponse(
        document_id=document_id,
        chain=[version_node(node) for node in chain],
    )
