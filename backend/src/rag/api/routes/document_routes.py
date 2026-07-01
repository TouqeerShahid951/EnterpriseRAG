from pathlib import Path
import re
from typing import Literal, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from ...auth.abac import normalize_group_path
from ...auth.dependencies import require_csrf, require_current_user
from ...auth.document_access import can_read_document, can_write_document
from ...auth.permissions import can_manage_group_path, is_global_admin
from ...core.config import settings
from ...graphrag.cleanup import (
    GraphRAGCleanupError,
    GraphRAGDeletionService,
    deletion_service_from_settings,
    partition_key_for_document,
)
from ...repositories.claims import ClaimRepository, get_claim_repository
from ...query.sources import source_from_hit
from ...query.http import ServiceRequestError
from ...query.qdrant import QdrantClient
from ...repositories.documents import DocumentRecord, DocumentRepository, IngestJobRecord, get_document_repository
from ...repositories.identity import IdentityRepository, UserRecord, get_identity_repository
from ...schemas.common import ErrorResponse
from ...schemas.docs import (
    DeleteDocumentResponse,
    Document,
    DocumentClaim,
    DocumentClearanceUpdateRequest,
    DocumentCrossReference,
    DocumentEntity,
    DocumentGraphEnrichmentResponse,
    DocumentListResponse,
    DocumentReingestResponse,
    DocumentSharesResponse,
    DocumentSharesUpdateRequest,
    DocumentTopicsUpdateRequest,
    DocumentUnshareRequest,
    SupersedeRequest,
    VersionNode,
    VersionChainResponse,
)
from ...schemas.query import SourceAnchor
from ...services.ingest_queue import IngestQueue, IngestQueueMessage, get_ingest_queue
from ...services.graphrag_queue import (
    GraphRAGDocumentIndexMessage,
    GraphRAGMaintenanceQueue,
    GraphRAGPartitionRebuildMessage,
    get_graphrag_maintenance_queue,
)
from ...services.document_image_asset_storage import DocumentImageAssetStorage, get_document_image_asset_storage
from ...services.upload_storage import UploadStorage, get_upload_storage
from ...shared.contracts.clearance import clearance_rank, normalize_clearance_level
from ...connectors.models import CONNECTOR_RECORD_CONTENT_TYPE

router = APIRouter(prefix="/docs", tags=["documents"])

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def get_document_qdrant_client() -> QdrantClient:
    return QdrantClient(
        base_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        timeout_seconds=settings.rag_http_timeout_seconds,
    )


def get_document_graphrag_deletion_service() -> GraphRAGDeletionService:
    return deletion_service_from_settings(settings)


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
    repo: DocumentRepository = Depends(get_document_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
) -> DocumentSharesResponse:
    require_csrf(request)
    if not is_global_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "document_share_forbidden", "message": "Only global administrators can share documents across Knowledge Spaces."},
        )
    document = require_visible_document(user, repo.get_document(document_id, include_deleted=True))
    shares = _validated_share_groups(payload.group_paths, document=document, identity_repo=identity_repo)
    updated = _replace_document_shares_with_index(
        document,
        shares,
        actor_id=user.id,
        repo=repo,
        qdrant=qdrant,
        event_type="documents.shares.replace",
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
    repo: DocumentRepository = Depends(get_document_repository),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
) -> DocumentSharesResponse:
    require_csrf(request)
    document = require_visible_document(user, repo.get_document(document_id, include_deleted=True))
    target_group = normalize_group_path(payload.group_path)
    if target_group not in document.shared_group_paths:
        return document_shares_to_schema(document)
    if not (is_global_admin(user) or can_manage_group_path(user, target_group)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "document_unshare_forbidden", "message": "Only global administrators or the target Space Admin can remove this share."},
        )
    updated = _replace_document_shares_with_index(
        document,
        [path for path in document.shared_group_paths if path != target_group],
        actor_id=user.id,
        repo=repo,
        qdrant=qdrant,
        event_type="documents.shares.unshare",
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
    repo: DocumentRepository = Depends(get_document_repository),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
) -> Document:
    require_csrf(request)
    document = require_writable_document(user, repo.get_document(document_id))
    try:
        target_clearance = normalize_clearance_level(payload.clearance_level)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_clearance_level", "message": str(exc)},
        ) from exc

    if clearance_rank(target_clearance) > clearance_rank(user.clearance_level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "clearance_forbidden",
                "message": "User cannot assign a clearance level above their own.",
            },
        )
    if target_clearance == document.clearance_level:
        return document_to_schema(document)

    current_rank = clearance_rank(document.clearance_level)
    target_rank = clearance_rank(target_clearance)
    indexed_first = target_rank > current_rank
    updated: DocumentRecord | None = None

    try:
        if indexed_first:
            _set_qdrant_document_clearance(qdrant, document.id, target_clearance)
        updated = repo.update_document_clearance(document.id, target_clearance)
        if updated is None:
            if indexed_first:
                _try_set_qdrant_document_clearance(qdrant, document.id, document.clearance_level)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "document_not_found", "message": "Document was not found."},
            )
        if not indexed_first:
            _set_qdrant_document_clearance(qdrant, document.id, target_clearance)
    except ServiceRequestError as exc:
        repo.append_audit_event(
            event_type="documents.clearance_update",
            actor_id=user.id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "old_clearance_level": document.clearance_level,
                "new_clearance_level": target_clearance,
                "action_result": "failed",
                "error_code": "document_clearance_index_update_failed",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "document_clearance_index_update_failed",
                "message": f"Unable to update indexed document clearance: {exc}",
            },
        ) from exc

    repo.append_audit_event(
        event_type="documents.clearance_update",
        actor_id=user.id,
        target_type="document",
        target_id=document.id,
        payload={
            "group_path": document.group_path,
            "old_clearance_level": document.clearance_level,
            "new_clearance_level": target_clearance,
            "qdrant_collection": settings.qdrant_collection,
            "action_result": "success",
        },
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
    repo: DocumentRepository = Depends(get_document_repository),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
) -> Document:
    require_csrf(request)
    document = require_writable_document(user, repo.get_document(document_id))
    topics = _normalize_topic_values(payload.topics)
    llm_topics = _normalize_topic_values(payload.llm_topics)
    indexed_topics = _unique_text([*topics, *llm_topics])
    if topics == list(document.topics) and llm_topics == list(document.llm_topics):
        return document_to_schema(document)

    updated = repo.update_document_topics(document.id, topics=topics, llm_topics=llm_topics)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "document_not_found", "message": "Document was not found."})
    try:
        qdrant.set_document_topics(document.id, topics=indexed_topics)
    except ServiceRequestError as exc:
        repo.update_document_topics(document.id, topics=list(document.topics), llm_topics=list(document.llm_topics))
        repo.append_audit_event(
            event_type="documents.topics_update",
            actor_id=user.id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "old_topics": list(document.topics),
                "old_llm_topics": list(document.llm_topics),
                "new_topics": topics,
                "new_llm_topics": llm_topics,
                "action_result": "failed",
                "error_code": "document_topics_index_update_failed",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "document_topics_index_update_failed",
                "message": f"Unable to update indexed document topics: {exc}",
            },
        ) from exc

    repo.append_audit_event(
        event_type="documents.topics_update",
        actor_id=user.id,
        target_type="document",
        target_id=document.id,
        payload={
            "group_path": document.group_path,
            "old_topics": list(document.topics),
            "old_llm_topics": list(document.llm_topics),
            "new_topics": topics,
            "new_llm_topics": llm_topics,
            "qdrant_collection": settings.qdrant_collection,
            "action_result": "success",
        },
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
    repo: DocumentRepository = Depends(get_document_repository),
) -> VersionChainResponse:
    require_csrf(request)
    new_doc = require_writable_document(user, repo.get_document(document_id))
    old_docs = [require_writable_document(user, repo.get_document(old_id)) for old_id in payload.supersedes]
    try:
        repo.mark_superseded(new_doc_id=new_doc.id, old_doc_ids=[doc.id for doc in old_docs])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_supersession", "message": str(exc)}) from exc
    repo.append_audit_event(
        event_type="documents.supersede",
        actor_id=user.id,
        target_type="document",
        target_id=new_doc.id,
        payload={"supersedes": [doc.id for doc in old_docs]},
    )
    chain = repo.list_version_chain(document_id)
    return VersionChainResponse(document_id=document_id, chain=[version_node(node) for node in chain])


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
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> DocumentReingestResponse:
    require_csrf(request)
    document = require_writable_document(user, repo.get_document(document_id))
    job = _queue_document_reingest(
        document,
        action="reingest",
        repo=repo,
        storage=storage,
        queue=queue,
        actor_id=user.id,
    )
    return DocumentReingestResponse(document_id=document.id, job_id=job.id)


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
    repo: DocumentRepository = Depends(get_document_repository),
    queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> DocumentGraphEnrichmentResponse:
    require_csrf(request)
    document = require_writable_document(user, repo.get_document(document_id))
    if not settings.graphrag_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "graphrag_disabled", "message": "Graph enrichment is disabled for this workspace."},
        )
    job = next(
        (candidate for candidate in repo.list_ingest_jobs() if candidate.doc_id == document.id and candidate.status == "complete"),
        None,
    )
    if document.ingest_status != "complete" or job is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "document_not_indexed", "message": "Graph enrichment is available after document indexing completes."},
        )
    try:
        queue.enqueue_document_index(
            GraphRAGDocumentIndexMessage(doc_id=document.id, job_id=job.id, reason="user_request")
        )
    except Exception as exc:
        repo.append_audit_event(
            event_type="documents.graph_enrichment.enqueue_failed",
            actor_id=user.id,
            target_type="document",
            target_id=document.id,
            payload={"job_id": job.id, "error": str(exc)[:300]},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "graphrag_enqueue_failed", "message": "Graph enrichment could not be queued."},
        ) from exc
    repo.append_audit_event(
        event_type="documents.graph_enrichment.queued",
        actor_id=user.id,
        target_type="document",
        target_id=document.id,
        payload={"job_id": job.id, "reason": "user_request"},
    )
    return DocumentGraphEnrichmentResponse(document_id=document.id, job_id=job.id)


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
    repo: DocumentRepository = Depends(get_document_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> DocumentReingestResponse:
    require_csrf(request)
    document = require_writable_document(user, repo.get_document(document_id, include_deleted=True))
    if document.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "document_not_deleted", "message": "Document is not in Trash."},
        )
    if repo.get_active_ingest_job_for_document(document.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "document_ingest_active", "message": "Document already has an active ingestion job."},
        )
    source = _read_reingest_source(document, storage)
    restored = repo.restore_document(document.id)
    if restored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "document_not_found", "message": "Document was not found."})
    job = _queue_document_reingest(
        restored,
        action="restore",
        repo=repo,
        storage=storage,
        queue=queue,
        actor_id=user.id,
        skip_active_job_check=True,
        source=source,
    )
    return DocumentReingestResponse(document_id=restored.id, job_id=job.id)


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
    repo: DocumentRepository = Depends(get_document_repository),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
    graphrag: GraphRAGDeletionService = Depends(get_document_graphrag_deletion_service),
    graphrag_queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> DeleteDocumentResponse:
    require_csrf(request)
    document = require_writable_document(user, repo.get_document(document_id))
    graph_cleanup = _delete_document_graphrag(
        document,
        event_type="documents.delete",
        actor_id=user.id,
        repo=repo,
        graphrag=graphrag,
    )
    try:
        qdrant.delete_document_points(document.id)
    except ServiceRequestError as exc:
        repo.append_audit_event(
            event_type="documents.delete",
            actor_id=user.id,
            target_type="document",
            target_id=document.id,
            payload={"group_path": document.group_path, "action_result": "failed", "error_code": "document_vectors_delete_failed"},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "document_vectors_delete_failed", "message": f"Unable to delete indexed document vectors: {exc}"},
        ) from exc
    deleted = repo.soft_delete_document(document.id)
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "document_not_found", "message": "Document was not found."})
    graph_rebuild_status = _enqueue_graphrag_partition_rebuild(
        document,
        event_type="documents.delete",
        actor_id=user.id,
        repo=repo,
        queue=graphrag_queue,
        partition_key=graph_cleanup.partition_key,
    )
    repo.append_audit_event(
        event_type="documents.delete",
        actor_id=user.id,
        target_type="document",
        target_id=document.id,
        payload={
            "group_path": document.group_path,
            "action_result": "success",
            "qdrant_collection": settings.qdrant_collection,
            "graphrag_cleanup_status": graph_cleanup.status,
            "graphrag_partition_key": graph_cleanup.partition_key,
            "graphrag_rebuild_status": graph_rebuild_status,
        },
    )
    return DeleteDocumentResponse(id=document.id)


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
    repo: DocumentRepository = Depends(get_document_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    image_storage: DocumentImageAssetStorage = Depends(get_document_image_asset_storage),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
    graphrag: GraphRAGDeletionService = Depends(get_document_graphrag_deletion_service),
    graphrag_queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> DeleteDocumentResponse:
    require_csrf(request)
    document = require_visible_document(user, repo.get_document(document_id, include_deleted=True))
    if not _can_permanently_delete_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "document_forbidden", "message": "Only platform admins and scoped Space Admins can permanently delete documents."},
        )
    graph_cleanup = _delete_document_graphrag(
        document,
        event_type="documents.permanent_delete",
        actor_id=user.id,
        repo=repo,
        graphrag=graphrag,
    )
    try:
        qdrant.delete_document_points(document.id)
        for asset in repo.list_document_image_assets(document.id):
            image_storage.delete(asset.object_path)
        if document.file_path:
            storage.delete(document.file_path)
    except ServiceRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "document_vectors_delete_failed", "message": f"Unable to delete indexed document vectors: {exc}"},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "document_file_delete_failed", "message": f"Unable to delete uploaded document file: {exc}"},
        ) from exc

    deleted = repo.permanently_delete_document(document.id)
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "document_not_found", "message": "Document was not found."})
    graph_rebuild_status = _enqueue_graphrag_partition_rebuild(
        document,
        event_type="documents.permanent_delete",
        actor_id=user.id,
        repo=repo,
        queue=graphrag_queue,
        partition_key=graph_cleanup.partition_key,
    )
    repo.append_audit_event(
        event_type="documents.permanent_delete",
        actor_id=user.id,
        target_type="document",
        target_id=document.id,
        payload={
            "file_path": document.file_path,
            "group_path": document.group_path,
            "qdrant_collection": settings.qdrant_collection,
            "action_result": "success",
            "graphrag_cleanup_status": graph_cleanup.status,
            "graphrag_partition_key": graph_cleanup.partition_key,
            "graphrag_rebuild_status": graph_rebuild_status,
        },
    )
    return DeleteDocumentResponse(id=document.id, status="permanently_deleted")


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


def _can_permanently_delete_document(user: UserRecord, document: DocumentRecord) -> bool:
    if document.shared_group_paths:
        return is_global_admin(user)
    return can_manage_group_path(user, document.group_path)


def _delete_document_graphrag(
    document: DocumentRecord,
    *,
    event_type: str,
    actor_id: str,
    repo: DocumentRepository,
    graphrag: GraphRAGDeletionService,
):
    partition_key = partition_key_for_document(document)
    try:
        return graphrag.delete_document(doc_id=document.id, partition_key=partition_key)
    except GraphRAGCleanupError as exc:
        repo.append_audit_event(
            event_type=event_type,
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "action_result": "failed",
                "error_code": "document_graphrag_delete_failed",
                "graphrag_partition_key": partition_key,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "document_graphrag_delete_failed",
                "message": f"Unable to delete GraphRAG document data: {exc}",
            },
        ) from exc


def _enqueue_graphrag_partition_rebuild(
    document: DocumentRecord,
    *,
    event_type: str,
    actor_id: str,
    repo: DocumentRepository,
    queue: GraphRAGMaintenanceQueue,
    partition_key: str | None,
) -> str:
    if not settings.graphrag_enabled:
        return "skipped"
    if not partition_key:
        return "skipped_missing_partition"
    try:
        queue.enqueue_partition_rebuild(
            GraphRAGPartitionRebuildMessage(
                doc_id=document.id,
                partition_key=partition_key,
                reason=event_type,
            )
        )
    except RuntimeError as exc:
        repo.append_audit_event(
            event_type=event_type,
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "action_result": "warning",
                "warning_code": "graphrag_rebuild_enqueue_failed",
                "graphrag_partition_key": partition_key,
                "message": str(exc)[:240],
            },
        )
        return "enqueue_failed"
    return "queued"


def _set_qdrant_document_clearance(qdrant: QdrantClient, document_id: str, clearance_level: str) -> None:
    qdrant.set_document_clearance(
        document_id,
        clearance_level=clearance_level,
        clearance_rank=clearance_rank(clearance_level),
    )


def _try_set_qdrant_document_clearance(qdrant: QdrantClient, document_id: str, clearance_level: str) -> None:
    try:
        _set_qdrant_document_clearance(qdrant, document_id, clearance_level)
    except ServiceRequestError:
        return


def _set_qdrant_document_acl(qdrant: QdrantClient, document_id: str, access_group_paths: list[str]) -> None:
    qdrant.set_document_acl_group_paths(document_id, acl_group_paths=access_group_paths)


def _try_set_qdrant_document_acl(qdrant: QdrantClient, document_id: str, access_group_paths: list[str]) -> None:
    try:
        _set_qdrant_document_acl(qdrant, document_id, access_group_paths)
    except ServiceRequestError:
        return


def _replace_document_shares_with_index(
    document: DocumentRecord,
    shares: list[str],
    *,
    actor_id: str | None,
    repo: DocumentRepository,
    qdrant: QdrantClient,
    event_type: str,
) -> DocumentRecord:
    old_shares = list(document.shared_group_paths)
    old_acl = list(document.access_group_paths)
    next_acl = _document_acl_group_paths(document.group_path, shares)
    removes_access = bool(set(old_acl) - set(next_acl))
    updated: DocumentRecord | None = None
    try:
        if removes_access:
            _set_qdrant_document_acl(qdrant, document.id, next_acl)
        updated = repo.replace_document_shares(document.id, group_paths=shares, actor_id=actor_id)
        if updated is None:
            if removes_access:
                _try_set_qdrant_document_acl(qdrant, document.id, old_acl)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "document_not_found", "message": "Document was not found."})
        if not removes_access:
            _set_qdrant_document_acl(qdrant, document.id, next_acl)
    except ServiceRequestError as exc:
        repo.replace_document_shares(document.id, group_paths=old_shares, actor_id=actor_id)
        repo.append_audit_event(
            event_type=event_type,
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload={
                "group_path": document.group_path,
                "old_shared_group_paths": old_shares,
                "new_shared_group_paths": shares,
                "action_result": "failed",
                "error_code": "document_acl_index_update_failed",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "document_acl_index_update_failed", "message": f"Unable to update indexed document ACL: {exc}"},
        ) from exc
    repo.append_audit_event(
        event_type=event_type,
        actor_id=actor_id,
        target_type="document",
        target_id=document.id,
        payload={
            "group_path": document.group_path,
            "old_shared_group_paths": old_shares,
            "new_shared_group_paths": list(updated.shared_group_paths),
            "qdrant_collection": settings.qdrant_collection,
            "action_result": "success",
        },
    )
    return updated


def _validated_share_groups(group_paths: list[str], *, document: DocumentRecord, identity_repo: IdentityRepository) -> list[str]:
    known = {group.path for group in identity_repo.list_groups()}
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in group_paths:
        try:
            group_path = normalize_group_path(raw_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_group_path", "message": str(exc)}) from exc
        if group_path == document.group_path:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_document_share", "message": "The owner Knowledge Space already has access and cannot be added as a share."},
            )
        if group_path not in known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "group_not_found", "message": f"Knowledge Space does not exist: {group_path}"},
            )
        if group_path not in seen:
            seen.add(group_path)
            normalized.append(group_path)
    return normalized


def _document_acl_group_paths(owner_group_path: str, shared_group_paths: list[str]) -> list[str]:
    normalized_owner = normalize_group_path(owner_group_path)
    paths = [normalized_owner, *[normalize_group_path(path) for path in shared_group_paths]]
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def _queue_document_reingest(
    document: DocumentRecord,
    *,
    action: str,
    repo: DocumentRepository,
    storage: UploadStorage,
    queue: IngestQueue,
    actor_id: str | None,
    skip_active_job_check: bool = False,
    source: object | None = None,
) -> IngestJobRecord:
    if not skip_active_job_check and repo.get_active_ingest_job_for_document(document.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "document_ingest_active", "message": "Document already has an active ingestion job."},
        )
    stored = source or _read_reingest_source(document, storage)
    job = repo.create_ingest_job(doc_id=document.id, status="queued", progress_pct=0, origin=action)
    message = _ingest_message_for_document(document, job.id, stored, repo)
    try:
        queue.enqueue(message)
    except RuntimeError as exc:
        repo.update_ingest_job(job.id, status="failed", progress_pct=0, error_code="queue_unavailable", error_message_safe=str(exc))
        repo.append_audit_event(
            event_type=f"documents.{action}",
            actor_id=actor_id,
            target_type="document",
            target_id=document.id,
            payload={"group_path": document.group_path, "clearance_level": document.clearance_level, "job_id": job.id, "action_result": "failed", "error_code": "queue_unavailable"},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "queue_unavailable", "message": "Ingestion queue is unavailable."},
        ) from exc
    repo.append_audit_event(
        event_type=f"documents.{action}",
        actor_id=actor_id,
        target_type="document",
        target_id=document.id,
        payload={"group_path": document.group_path, "clearance_level": document.clearance_level, "job_id": job.id, "action_result": "success"},
    )
    return job


def _read_reingest_source(document: DocumentRecord, storage: UploadStorage) -> object:
    if not document.file_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "document_source_missing", "message": "Document does not have a stored source file."},
        )
    try:
        return storage.read(document.file_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "document_source_missing", "message": "Document source file was not found."},
        ) from exc


def _ingest_message_for_document(document: DocumentRecord, job_id: str, stored: object, repo: DocumentRepository) -> IngestQueueMessage:
    filename = str(getattr(stored, "filename", "") or _filename_for_document(document))
    content_type = getattr(stored, "content_type", None) or _content_type_for_filename(filename)
    supersedes = repo.list_superseded_document_ids(document.id) or list(document.pending_supersedes)
    return IngestQueueMessage(
        job_id=job_id,
        doc_id=document.id,
        file_path=str(document.file_path),
        group_path=document.group_path,
        acl_group_paths=list(document.access_group_paths),
        clearance_level=document.clearance_level,
        doc_type=document.doc_type,
        effective_date=document.effective_date.isoformat() if document.effective_date else None,
        supersedes=supersedes,
        expiry_date=document.expiry_date.isoformat() if document.expiry_date else None,
        description=document.description,
        content_type=str(content_type) if content_type else None,
    )


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


def _normalize_topic_values(values: list[str]) -> list[str]:
    topics = _unique_text(values)
    too_long = [topic for topic in topics if len(topic) > 80]
    if too_long:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_topic", "message": "Topic labels must be 80 characters or fewer."},
        )
    return topics[:32]


def _unique_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            normalized.append(text)
    return normalized


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
