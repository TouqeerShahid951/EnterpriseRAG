"""Document binary content and indexed-source HTTP routes."""

from pathlib import Path
import re
from hashlib import sha256
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Path as ApiPath, Query, Response, status
from fastapi.responses import StreamingResponse

from ...auth.dependencies import require_current_user
from ...auth.identity_models import UserRecord
from ...connectors.models import CONNECTOR_RECORD_CONTENT_TYPE
from ...core.config import settings
from ...query.http import ServiceRequestError
from ...query.qdrant import QdrantClient
from ...ingestion.publication.models import generation_id_for_job
from ...ingestion.publication.dependencies import active_generation_resolver_for
from rag.query.sources import source_from_hit
from rag.shared.contracts.http import ErrorResponse
from ...shared.contracts.evidence import SourceAnchor
from ..dependencies import get_document_image_asset_storage, get_upload_storage
from ..image_asset_storage import DocumentImageAssetStorage
from ..repository import DocumentImageAssetRecord, DocumentRecord, DocumentRepository, get_document_repository
from ..storage import UploadStorage
from ..schemas import DocumentSlidesResponse
from ..source_revision import SourceRevision
from .authorization import require_visible_document

router = APIRouter(prefix="/docs")

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def get_document_qdrant_client() -> QdrantClient:
    return QdrantClient(
        base_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        timeout_seconds=settings.rag_http_timeout_seconds,
        active_generation_resolver=active_generation_resolver_for(settings),
    )


def expected_source_revision(
    generation_id: str | None = Query(default=None, min_length=1, max_length=200),
    content_hash: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$"),
) -> SourceRevision:
    return SourceRevision(generation_id, content_hash)


def require_source_revision(document: DocumentRecord, expected: SourceRevision) -> None:
    if not expected.matches(document):
        raise HTTPException(status_code=404, detail={"code": "source_revision_unavailable",
            "message": "The cited source revision is no longer available."})


@router.get(
    "/{document_id}/content",
    responses={
        status.HTTP_200_OK: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "text/csv": {},
                "image/jpeg": {},
                "image/png": {},
                "application/json": {},
                CONNECTOR_RECORD_CONTENT_TYPE: {},
            }
        },
        status.HTTP_206_PARTIAL_CONTENT: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "text/csv": {},
                "image/jpeg": {},
                "image/png": {},
                "application/json": {},
                CONNECTOR_RECORD_CONTENT_TYPE: {},
            }
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Stream original document content",
)
async def get_document_content(
    document_id: str,
    expected: SourceRevision = Depends(expected_source_revision),
    range_header: str | None = Header(default=None, alias="Range"),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    storage: UploadStorage = Depends(get_upload_storage),
) -> Response:
    document = require_visible_document(user, repo.get_document(document_id))
    require_source_revision(document, expected)
    if not document.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "document_file_not_found",
                "message": "Document file was not found.",
            },
        )
    try:
        stored = storage.read(document.file_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "document_file_not_found",
                "message": "Document file was not found.",
            },
        ) from exc

    content = stored.content
    content_revision = SourceRevision(expected.generation_id, expected.content_hash or (document.content_hash if expected.generation_id else None))
    if (expected.generation_id and not content_revision.content_hash) or not content_revision.matches_content(content):
        raise HTTPException(status_code=404, detail={"code": "source_revision_unavailable", "message": "The cited source revision is no longer available."})
    require_source_revision(require_visible_document(user, repo.get_document(document_id)), expected)
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
            return Response(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={**headers, "Content-Range": f"bytes */{total}"},
            )
        start, end = byte_range
        body = content[start : end + 1]
        return StreamingResponse(
            iter([body]),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=content_type,
            headers={
                **headers,
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(len(body)),
            },
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
    expected: SourceRevision = Depends(expected_source_revision),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    storage: DocumentImageAssetStorage = Depends(get_document_image_asset_storage),
) -> Response:
    document = require_visible_document(user, repo.get_document(document_id))
    require_source_revision(document, expected)
    asset = repo.get_document_image_asset(document.id, asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "image_asset_not_found",
                "message": "Image asset was not found.",
            },
        )
    if expected.generation_id and (not asset.job_id or generation_id_for_job(asset.job_id) != expected.generation_id):
        raise HTTPException(status_code=404, detail={"code": "source_revision_unavailable", "message": "The cited source revision is no longer available."})
    response = _stream_image_asset(asset, storage)
    require_source_revision(require_visible_document(user, repo.get_document(document_id)), expected)
    return response


@router.get(
    "/{document_id}/slides",
    response_model=DocumentSlidesResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
    summary="List available rendered presentation slides",
)
async def list_document_slides(
    document_id: str,
    expected: SourceRevision = Depends(expected_source_revision),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
) -> DocumentSlidesResponse:
    document = require_visible_document(user, repo.get_document(document_id))
    require_source_revision(document, expected)
    assets = repo.list_document_image_assets(document.id)
    require_source_revision(require_visible_document(user, repo.get_document(document_id)), expected)
    return DocumentSlidesResponse(slides=sorted({
        asset.page for asset in assets
        if (not expected.generation_id or (asset.job_id and generation_id_for_job(asset.job_id) == expected.generation_id))
        and asset.source_kind == "pptx_slide" and asset.page is not None and asset.page > 0
    }))


@router.get(
    "/{document_id}/slides/{slide_number}/content",
    responses={
        status.HTTP_200_OK: {"content": {"image/png": {}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Stream a rendered presentation slide",
)
async def get_document_slide_content(
    document_id: str,
    slide_number: Annotated[int, ApiPath(ge=1)],
    expected: SourceRevision = Depends(expected_source_revision),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    storage: DocumentImageAssetStorage = Depends(get_document_image_asset_storage),
) -> Response:
    document = require_visible_document(user, repo.get_document(document_id))
    require_source_revision(document, expected)
    asset = next(
        (
            item
            for item in repo.list_document_image_assets(document.id)
            if item.source_kind == "pptx_slide" and item.page == slide_number
        ),
        None,
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "presentation_slide_not_found",
                "message": "Rendered presentation slide was not found.",
            },
        )
    if expected.generation_id and (not asset.job_id or generation_id_for_job(asset.job_id) != expected.generation_id):
        raise HTTPException(status_code=404, detail={"code": "source_revision_unavailable", "message": "The cited source revision is no longer available."})
    response = _stream_image_asset(asset, storage)
    require_source_revision(require_visible_document(user, repo.get_document(document_id)), expected)
    return response


def _stream_image_asset(asset: DocumentImageAssetRecord, storage: DocumentImageAssetStorage) -> Response:
    try:
        stored = storage.read(asset.object_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "image_asset_file_not_found",
                "message": "Image asset file was not found.",
            },
        ) from exc
    if asset.content_hash and sha256(stored.content).hexdigest() != asset.content_hash:
        raise HTTPException(status_code=404, detail={"code": "source_revision_unavailable", "message": "The cited source revision is no longer available."})
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
    expected: SourceRevision = Depends(expected_source_revision),
    evidence_hash: str | None = Query(default=None, pattern=r"^[a-f0-9]{64}$"),
    user: UserRecord = Depends(require_current_user),
    repo: DocumentRepository = Depends(get_document_repository),
    qdrant: QdrantClient = Depends(get_document_qdrant_client),
) -> SourceAnchor:
    document = require_visible_document(user, repo.get_document(document_id))
    require_source_revision(document, expected)
    try:
        hit = qdrant.retrieve_source_chunk(doc_id=document.id, chunk_id=chunk_id)
    except ServiceRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "source_lookup_failed",
                "message": f"Unable to read source location metadata: {exc}",
            },
        ) from exc
    if hit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "source_not_found",
                "message": "Source location was not found.",
            },
        )
    source = source_from_hit(hit)
    if (source.doc_id != document.id or source.chunk_id != chunk_id
            or (expected.generation_id and source.index_generation_id != expected.generation_id)
            or (expected.content_hash and source.content_hash != expected.content_hash)
            or (evidence_hash and sha256(source.excerpt.encode("utf-8")).hexdigest() != evidence_hash)):
        raise HTTPException(status_code=404, detail={"code": "source_revision_unavailable", "message": "The cited source revision is no longer available."})
    require_source_revision(require_visible_document(user, repo.get_document(document_id)), expected)
    return source


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
    if lowered.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if lowered.endswith(".csv"):
        return "text/csv"
    if lowered.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".json"):
        return "application/json"
    return "application/octet-stream"
