"""Document catalog and version-history HTTP routes."""

from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_current_user
from ...auth.document_access import can_read_document
from ...auth.identity_models import UserRecord
from ...auth.permissions import can_read_document_metadata, is_global_admin
from ...shared.contracts.clearance import clearance_levels_at_or_below
from rag.shared.contracts.http import ErrorResponse
from rag.documents.metadata.schemas import VersionChainResponse
from rag.documents.schemas import (
    Document,
    DocumentCatalogSummary,
    DocumentGroupCount,
    DocumentListResponse,
    DocumentOverviewResponse,
)
from ..claim_dependencies import get_claim_repository
from ..claim_models import ClaimRepository
from ..overview import build_document_overview
from ..repository import DocumentRepository, get_document_repository
from .authorization import require_visible_document
from .presenters import document_overview_to_schema, document_to_schema, version_node

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
    records = await run_in_threadpool(repo.list_documents, state=state_value)
    documents = [
        document_to_schema(document)
        for document in records
        if can_read_document(user, document)
        and _matches_group_filter(document.access_group_paths, normalized_group)
    ]
    return DocumentListResponse(items=documents, total=len(documents))


@router.get(
    "/summary",
    response_model=DocumentCatalogSummary,
    summary="Summarize visible documents by owner group",
)
async def summarize_documents(
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentCatalogSummary:
    if not can_read_document_metadata(user):
        return DocumentCatalogSummary(total=0)
    group_paths = (
        None
        if is_global_admin(user)
        else tuple(sorted({normalize_group_path(path) for path in user.group_paths}))
    )
    counts = await run_in_threadpool(
        repo.count_documents_by_owner_group,
        clearance_levels=clearance_levels_at_or_below(user.clearance_level),
        group_paths=group_paths,
    )
    groups = [
        DocumentGroupCount(group_path=group_path, count=count)
        for group_path, count in sorted(counts.items())
    ]
    return DocumentCatalogSummary(
        groups=groups,
        total=sum(group.count for group in groups),
    )


@router.get(
    "/overview",
    response_model=DocumentOverviewResponse,
    summary="Summarize the visible Document Library",
)
async def summarize_document_overview(
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentOverviewResponse:
    overview = await run_in_threadpool(
        build_document_overview,
        user=user,
        repository=repo,
    )
    return document_overview_to_schema(overview)


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
