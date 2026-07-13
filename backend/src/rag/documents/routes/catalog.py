"""Document catalog and version-history HTTP routes."""

from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_current_user
from ...auth.document_access import can_read_document
from ...auth.identity_models import UserRecord
from ...schemas.common import ErrorResponse
from ...schemas.docs import Document, DocumentListResponse, VersionChainResponse
from ..claim_dependencies import get_claim_repository
from ..claim_models import ClaimRepository
from ..repository import DocumentRepository, get_document_repository
from .authorization import require_visible_document
from .presenters import document_to_schema, version_node

router = APIRouter(prefix="/docs")


@router.get("", response_model=DocumentListResponse, summary="List visible documents")
async def list_documents(
    state: str = Query(default="active"),
    group_path: str | None = Query(default=None),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentListResponse:
    state_value = _document_state(state)
    normalized_group = normalize_group_path(group_path) if group_path else None
    documents = [
        document_to_schema(document)
        for document in repo.list_documents(state=state_value)
        if can_read_document(user, document)
        and _matches_group_filter(document.access_group_paths, normalized_group)
    ]
    return DocumentListResponse(items=documents, total=len(documents))


@router.get(
    "/{document_id}",
    responses={
        status.HTTP_200_OK: {"model": Document},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Read document metadata",
)
async def get_document(
    document_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    claim_repo: ClaimRepository = Depends(get_claim_repository),
) -> Document:
    document = repo.get_document(document_id, include_deleted=True)
    require_visible_document(user, document)
    return document_to_schema(
        document,
        entities=repo.list_document_entities(document.id),
        cross_references=repo.list_document_cross_references(document.id),
        claims=claim_repo.list_claims_for_document(document.id),
    )


@router.get(
    "/{document_id}/versions",
    responses={
        status.HTTP_200_OK: {"model": VersionChainResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Read a document supersession chain",
)
async def get_document_versions(
    document_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> VersionChainResponse:
    document = repo.get_document(document_id, include_deleted=True)
    require_visible_document(user, document)
    chain = [
        node
        for node in repo.list_version_chain(document_id)
        if can_read_document(user, node)
    ]
    return VersionChainResponse(
        document_id=document_id,
        chain=[version_node(node) for node in chain],
    )


def _document_state(value: str) -> Literal["active", "deleted"]:
    if value not in {"active", "deleted"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_document_state",
                "message": "Document state must be active or deleted.",
            },
        )
    return cast(Literal["active", "deleted"], value)


def _matches_group_filter(
    document_group_paths: tuple[str, ...],
    group_path: str | None,
) -> bool:
    if group_path is None:
        return True
    return any(
        normalize_group_path(document_group_path) == group_path
        for document_group_path in document_group_paths
    )
