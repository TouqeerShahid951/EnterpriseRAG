"""Public document routes."""

from collections.abc import Callable
from pathlib import Path
import re
from typing import Literal, TypeVar, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from ..auth.abac import normalize_group_path
from ..auth.dependencies import require_csrf, require_current_user
from ..auth.document_access import can_read_document, can_write_document
from ..core.config import settings
from .access_scope_dependencies import (
    get_document_access_scope_service,
)
from .access_scope_service import (
    DocumentAccessScopeRejected,
    DocumentAccessScopeService,
)
from .dependencies import get_upload_storage
from .lifecycle_dependencies import get_document_lifecycle_service
from .lifecycle_service import (
    DeleteDocumentCommand,
    DocumentLifecycleRejected,
    DocumentLifecycleService,
    RestoreDocumentCommand,
)
from .metadata_dependencies import get_document_metadata_service
from .metadata_service import (
    DocumentMetadataRejected,
    DocumentMetadataService,
)
from .storage import UploadStorage
from .claim_dependencies import get_claim_repository
from .claim_models import ClaimRepository
from ..query.sources import source_from_hit
from ..query.http import ServiceRequestError
from ..query.qdrant import QdrantClient
from .repository import DocumentRecord, DocumentRepository, get_document_repository
from ..auth.identity_models import UserRecord
from ..schemas.common import ErrorResponse
from ..schemas.docs import (
    DeleteDocumentResponse,
    Document,
    DocumentClaim,
    DocumentClearanceUpdateRequest,
    DocumentCrossReference,
    DocumentEntity,
    DocumentListResponse,
    DocumentOwnerUpdateRequest,
    DocumentReingestResponse,
    DocumentSharesResponse,
    DocumentSharesUpdateRequest,
    DocumentTopicsUpdateRequest,
    DocumentUnshareRequest,
    SupersedeRequest,
    VersionNode,
    VersionChainResponse,
)
from ..schemas.query import SourceAnchor
from ..services.document_image_asset_storage import DocumentImageAssetStorage, get_document_image_asset_storage
from ..connectors.models import CONNECTOR_RECORD_CONTENT_TYPE

router = APIRouter(prefix="/docs", tags=["documents"])

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")

_ACCESS_SCOPE_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "invalid": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "upstream": status.HTTP_502_BAD_GATEWAY,
}

_METADATA_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "invalid": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "bad_request": status.HTTP_400_BAD_REQUEST,
    "upstream": status.HTTP_502_BAD_GATEWAY,
}

_DOCUMENT_OPERATION_STATUS_BY_CATEGORY = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "forbidden": status.HTTP_403_FORBIDDEN,
    "conflict": status.HTTP_409_CONFLICT,
    "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "bad_gateway": status.HTTP_502_BAD_GATEWAY,
}

MetadataResult = TypeVar("MetadataResult")
LifecycleResult = TypeVar("LifecycleResult")


def get_document_qdrant_client() -> QdrantClient:
    return QdrantClient(
        base_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        timeout_seconds=settings.rag_http_timeout_seconds,
    )


def _access_scope_result(
    action: Callable[[], DocumentRecord],
) -> DocumentRecord:
    try:
        return action()
    except DocumentAccessScopeRejected as exc:
        raise HTTPException(
            status_code=_ACCESS_SCOPE_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def _metadata_result(
    action: Callable[[], MetadataResult],
) -> MetadataResult:
    try:
        return action()
    except DocumentMetadataRejected as exc:
        raise HTTPException(
            status_code=_METADATA_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def _lifecycle_result(
    action: Callable[[], LifecycleResult],
) -> LifecycleResult:
    try:
        return action()
    except DocumentLifecycleRejected as exc:
        raise HTTPException(
            status_code=_DOCUMENT_OPERATION_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


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
        if can_read_document(user, document) and _matches_group_filter(document.access_group_paths, normalized_group)
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
    document = require_visible_document(user, repo.get_document(document_id, include_deleted=True))
    return document_shares_to_schema(document)


@router.patch(
    "/{document_id}/owner",
    response_model=Document,
    responses={
        status.HTTP_200_OK: {"model": Document},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
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
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
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


@router.get(
    "/{document_id}/content",
    responses={
        status.HTTP_200_OK: {"content": {"application/pdf": {}, "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}, "image/jpeg": {}, "image/png": {}, "application/json": {}, CONNECTOR_RECORD_CONTENT_TYPE: {}}},
        status.HTTP_206_PARTIAL_CONTENT: {"content": {"application/pdf": {}, "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}, "image/jpeg": {}, "image/png": {}, "application/json": {}, CONNECTOR_RECORD_CONTENT_TYPE: {}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Stream original document content",
)
async def get_document_content(
    document_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    storage: UploadStorage = Depends(get_upload_storage),
) -> Response:
    document = require_visible_document(user, repo.get_document(document_id))
    if not document.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "document_file_not_found", "message": "Document file was not found."})
    try:
        stored = storage.read(document.file_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "document_file_not_found", "message": "Document file was not found."}) from exc

    content = stored.content
    total = len(content)
    filename = stored.filename or _filename_for_document(document)
    content_type = stored.content_type or _content_type_for_filename(filename)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": _inline_content_disposition(filename),
    }

    if range_header:
        byte_range = _parse_range(range_header, total)
        if byte_range is None:
            return Response(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, headers={**headers, "Content-Range": f"bytes */{total}"})
        start, end = byte_range
        body = content[start : end + 1]
        return StreamingResponse(
            iter([body]),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=content_type,
            headers={**headers, "Content-Range": f"bytes {start}-{end}/{total}", "Content-Length": str(len(body))},
        )

    return StreamingResponse(
        iter([content]),
        media_type=content_type,
        headers={**headers, "Content-Length": str(total)},
    )


@router.get(
    "/{document_id}/image-assets/{asset_id}/content",
    responses={
        status.HTTP_200_OK: {"content": {"image/jpeg": {}, "image/png": {}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Stream an extracted document image asset",
)
async def get_document_image_asset_content(
    document_id: str,
    asset_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    storage: DocumentImageAssetStorage = Depends(get_document_image_asset_storage),
) -> Response:
    document = require_visible_document(user, repo.get_document(document_id))
    asset = repo.get_document_image_asset(document.id, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "image_asset_not_found", "message": "Image asset was not found."})
    try:
        stored = storage.read(asset.object_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "image_asset_file_not_found", "message": "Image asset file was not found."}) from exc
    return StreamingResponse(
        iter([stored.content]),
        media_type=stored.content_type or asset.content_type,
        headers={
            "Content-Length": str(len(stored.content)),
            "Content-Disposition": _inline_content_disposition(stored.filename),
        },
    )


@router.get(
    "/{document_id}/sources/{chunk_id:path}",
    responses={
        status.HTTP_200_OK: {"model": SourceAnchor},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
    summary="Read indexed source location metadata for a document chunk",
)
async def get_document_source(
    document_id: str,
    chunk_id: str,
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
) -> SourceAnchor:
    document = require_visible_document(user, repo.get_document(document_id))
    try:
        hit = qdrant.retrieve_source_chunk(doc_id=document.id, chunk_id=chunk_id)
    except ServiceRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "source_lookup_failed", "message": f"Unable to read source location metadata: {exc}"},
        ) from exc
    if hit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "source_not_found", "message": "Source location was not found."})
    return source_from_hit(hit)


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
    chain = [node for node in repo.list_version_chain(document_id) if can_read_document(user, node)]
    return VersionChainResponse(document_id=document_id, chain=[version_node(node) for node in chain])


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
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
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
    return VersionChainResponse(document_id=document_id, chain=[version_node(node) for node in chain])


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


def _document_state(value: str) -> Literal["active", "deleted"]:
    if value not in {"active", "deleted"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_document_state", "message": "Document state must be active or deleted."},
        )
    return cast(Literal["active", "deleted"], value)


def _matches_group_filter(document_group_paths: tuple[str, ...], group_path: str | None) -> bool:
    if group_path is None:
        return True
    return any(normalize_group_path(document_group_path) == group_path for document_group_path in document_group_paths)


def document_to_schema(
    document: DocumentRecord,
    *,
    entities: list[object] | None = None,
    cross_references: list[object] | None = None,
    claims: list[object] | None = None,
) -> Document:
    return Document(
        id=document.id,
        title=document.title or document.source_id,
        doc_type=document.doc_type,
        group_path=document.group_path,
        owner_group_path=document.owner_group_path,
        shared_group_paths=list(document.shared_group_paths),
        access_group_paths=list(document.access_group_paths),
        governance_owner=document.governance_owner,
        clearance_level=document.clearance_level,
        effective_date=document.effective_date.isoformat() if document.effective_date else None,
        expiry_date=document.expiry_date.isoformat() if document.expiry_date else None,
        description=document.description,
        summary=document.summary,
        language=document.language,
        topics=list(document.topics),
        llm_topics=list(document.llm_topics),
        metadata_version=_metadata_version(document.metadata_flags),
        metadata_confidence=_dict_metadata_field(document.metadata_flags, "metadata_confidence"),
        metadata_provenance=_dict_metadata_field(document.metadata_flags, "metadata_provenance"),
        auto_doc_type=document.auto_doc_type,
        extracted_dates=document.extracted_dates,
        metadata_flags=document.metadata_flags,
        entities=[_entity_to_schema(entity) for entity in entities or []],
        cross_references=[_cross_reference_to_schema(ref) for ref in cross_references or []],
        claims=[_claim_to_schema(claim) for claim in claims or []],
        is_current=document.is_current,
        ingest_status=document.ingest_status,
        uploaded_by=document.uploaded_by or "local",
        superseded_by=document.superseded_by,
        deleted_at=document.deleted_at,
        created_at=document.created_at,
    )


def document_shares_to_schema(document: DocumentRecord) -> DocumentSharesResponse:
    return DocumentSharesResponse(
        document_id=document.id,
        owner_group_path=document.owner_group_path,
        shared_group_paths=list(document.shared_group_paths),
        access_group_paths=list(document.access_group_paths),
        governance_owner=document.governance_owner,
    )


def version_node(document: DocumentRecord) -> VersionNode:
    return VersionNode(
        id=document.id,
        effective_date=document.effective_date.isoformat() if document.effective_date else None,
        is_current=document.is_current,
        superseded_by=document.superseded_by,
    )


def _entity_to_schema(entity: object) -> DocumentEntity:
    return DocumentEntity(
        text=str(getattr(entity, "text")),
        type=str(getattr(entity, "type")),
        start=getattr(entity, "start"),
        end=getattr(entity, "end"),
    )


def _cross_reference_to_schema(ref: object) -> DocumentCrossReference:
    return DocumentCrossReference(
        ref_text=str(getattr(ref, "ref_text")),
        ref_type=str(getattr(ref, "ref_type")),
        position=getattr(ref, "position"),
    )


def _claim_to_schema(claim: object) -> DocumentClaim:
    return DocumentClaim(
        id=getattr(claim, "id"),
        chunk_id=str(getattr(claim, "chunk_id")),
        entity=str(getattr(claim, "entity")),
        attribute=str(getattr(claim, "attribute")),
        value=str(getattr(claim, "value")),
    )


def _metadata_version(flags: dict[str, object]) -> int | None:
    value = flags.get("metadata_version")
    return value if isinstance(value, int) else None


def _dict_metadata_field(flags: dict[str, object], key: str) -> dict[str, object]:
    value = flags.get(key)
    return dict(value) if isinstance(value, dict) else {}


def require_visible_document(user: UserRecord, document: DocumentRecord | None) -> DocumentRecord:
    if document is None or not can_read_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "document_not_found", "message": "Document was not found."},
        )
    return document


def require_writable_document(user: UserRecord, document: DocumentRecord | None) -> DocumentRecord:
    visible = require_visible_document(user, document)
    if not can_write_document(user, visible):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "document_forbidden", "message": "User cannot modify this document."},
        )
    return visible


def _parse_range(value: str, total: int) -> tuple[int, int] | None:
    match = RANGE_RE.match(value.strip())
    if not match or total < 0:
        return None
    raw_start, raw_end = match.groups()
    if raw_start == "" and raw_end == "":
        return None
    if raw_start == "":
        suffix_length = int(raw_end)
        if suffix_length <= 0:
            return None
        start = max(0, total - suffix_length)
        end = total - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else total - 1
    if start < 0 or end < start or start >= total:
        return None
    return start, min(end, total - 1)


def _inline_content_disposition(filename: str) -> str:
    safe_name = filename.replace('"', "'")
    encoded = quote(filename)
    return f'inline; filename="{safe_name}"; filename*=UTF-8\'\'{encoded}'


def _filename_for_document(document: DocumentRecord) -> str:
    if document.title and Path(document.title).suffix:
        return document.title
    if document.file_path:
        return Path(document.file_path).name
    return f"{document.id}.bin"


def _content_type_for_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".jpg") or lowered.endswith(".jpeg"):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".json"):
        return "application/json"
    return "application/octet-stream"
