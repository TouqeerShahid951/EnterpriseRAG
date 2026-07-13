"""Document ownership and Knowledge Space sharing HTTP routes."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...auth.dependencies import require_csrf, require_current_user
from ...auth.identity_models import UserRecord
from ...schemas.common import ErrorResponse
from ...schemas.docs import (
    Document,
    DocumentOwnerUpdateRequest,
    DocumentSharesResponse,
    DocumentSharesUpdateRequest,
    DocumentUnshareRequest,
)
from ..access_scope_dependencies import get_document_access_scope_service
from ..access_scope_service import (
    DocumentAccessScopeRejected,
    DocumentAccessScopeService,
)
from ..repository import DocumentRecord, DocumentRepository, get_document_repository
from .authorization import require_visible_document
from .presenters import document_shares_to_schema, document_to_schema

router = APIRouter(prefix="/docs")

_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "upstream": status.HTTP_502_BAD_GATEWAY,
}


def _access_scope_result(action: Callable[[], DocumentRecord]) -> DocumentRecord:
    try:
        return action()
    except DocumentAccessScopeRejected as exc:
        raise HTTPException(
            status_code=_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get(
    "/{document_id}/shares",
    response_model=DocumentSharesResponse,
    responses={
        status.HTTP_200_OK: {"model": DocumentSharesResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Read document Knowledge Space shares",
)
async def get_document_shares(
    document_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentSharesResponse:
    document = require_visible_document(
        user,
        repo.get_document(document_id, include_deleted=True),
    )
    return document_shares_to_schema(document)


@router.patch(
    "/{document_id}/owner",
    response_model=Document,
    responses={
        status.HTTP_200_OK: {"model": Document},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
    summary="Transfer document ownership to another Knowledge Space",
)
async def transfer_document_owner(
    document_id: str,
    payload: DocumentOwnerUpdateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentAccessScopeService = Depends(
        get_document_access_scope_service
    ),
) -> Document:
    require_csrf(request)
    updated = _access_scope_result(
        lambda: service.transfer_owner(
            document_id,
            target_group_path=payload.group_path,
            actor=user,
        )
    )
    return document_to_schema(updated)


@router.put(
    "/{document_id}/shares",
    response_model=DocumentSharesResponse,
    responses={
        status.HTTP_200_OK: {"model": DocumentSharesResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
    summary="Replace document Knowledge Space shares",
)
async def replace_document_shares(
    document_id: str,
    payload: DocumentSharesUpdateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentAccessScopeService = Depends(
        get_document_access_scope_service
    ),
) -> DocumentSharesResponse:
    require_csrf(request)
    updated = _access_scope_result(
        lambda: service.replace_shares(
            document_id,
            group_paths=payload.group_paths,
            actor=user,
        )
    )
    return document_shares_to_schema(updated)


@router.post(
    "/{document_id}/shares/unshare",
    response_model=DocumentSharesResponse,
    responses={
        status.HTTP_200_OK: {"model": DocumentSharesResponse},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
    summary="Remove one shared Knowledge Space from a document",
)
async def unshare_document(
    document_id: str,
    payload: DocumentUnshareRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: DocumentAccessScopeService = Depends(
        get_document_access_scope_service
    ),
) -> DocumentSharesResponse:
    require_csrf(request)
    updated = _access_scope_result(
        lambda: service.unshare(
            document_id,
            target_group_path=payload.group_path,
            actor=user,
        )
    )
    return document_shares_to_schema(updated)
