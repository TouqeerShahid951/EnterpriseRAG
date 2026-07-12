from fastapi import APIRouter, Depends, HTTPException, status

from ..documents.models import DocumentCrossReferenceRecord, DocumentEntityRecord
from ..documents.repository import DocumentRepository, get_document_repository
from ..schemas.internal import DocumentImageAssetsReplaceRequest, DocumentImageAssetsReplaceResponse, DocumentMetadataSaveRequest, InternalMutationResponse, InternalSupersedeRequest, ServiceTokenContext
from ..services.document_image_asset_storage import DocumentImageAssetStorage, get_document_image_asset_storage
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-docs"])


@router.post(
    "/docs/{new_doc_id}/supersede",
    response_model=InternalMutationResponse,
    summary="Commit an ingestion-driven supersession update",
)
async def supersede_documents_internal(
    new_doc_id: str,
    payload: InternalSupersedeRequest,
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
    try:
        updated = document_repo.mark_superseded(new_doc_id=new_doc_id, old_doc_ids=payload.supersedes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_supersession", "message": str(exc)},
        ) from exc

    document_repo.append_audit_event(
        event_type="internal.supersession.committed",
        actor_id=None,
        target_type="document",
        target_id=new_doc_id,
        payload={"superseded_doc_ids": [document.id for document in updated]},
    )
    return InternalMutationResponse()


@router.post(
    "/docs/{doc_id}/metadata",
    response_model=InternalMutationResponse,
    summary="Persist extracted ingestion metadata",
)
async def save_document_metadata_internal(
    doc_id: str,
    payload: DocumentMetadataSaveRequest,
    document_repo: DocumentRepository = Depends(get_document_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> InternalMutationResponse:
    _ = service
    metadata_flags = _metadata_flags_with_v2(payload)
    document = document_repo.save_document_metadata(
        document_id=doc_id,
        summary=payload.summary,
        language=payload.language,
        topics=payload.topics,
        llm_topics=payload.llm_topics,
        doc_type=payload.doc_type,
        auto_doc_type=payload.auto_doc_type,
        extracted_dates=payload.extracted_dates,
        metadata_flags=metadata_flags,
        entities=[
            DocumentEntityRecord(
                doc_id=doc_id,
                text=entity.text,
                type=entity.type,
                start=entity.start,
                end=entity.end,
            )
            for entity in payload.entities
        ],
        cross_references=[
            DocumentCrossReferenceRecord(
                doc_id=doc_id,
                ref_text=ref.ref_text,
                ref_type=ref.ref_type,
                position=ref.position,
            )
            for ref in payload.cross_references
        ],
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "document_not_found", "message": "Document was not found."},
        )
    document_repo.append_audit_event(
        event_type="internal.document_metadata.saved",
        actor_id=None,
        target_type="document",
        target_id=doc_id,
        payload={
            "topics_count": len(payload.topics),
            "llm_topics_count": len(payload.llm_topics),
            "doc_type": payload.doc_type,
            "metadata_version": payload.metadata_version,
            "entities_count": len(payload.entities),
            "cross_references_count": len(payload.cross_references),
        },
    )
    return InternalMutationResponse()


def _metadata_flags_with_v2(payload: DocumentMetadataSaveRequest) -> dict[str, object]:
    flags: dict[str, object] = dict(payload.metadata_flags)
    if payload.metadata_version is not None:
        flags["metadata_version"] = payload.metadata_version
    if payload.metadata_confidence:
        flags["metadata_confidence"] = payload.metadata_confidence
    if payload.metadata_provenance:
        flags["metadata_provenance"] = payload.metadata_provenance
    return flags


@router.post(
    "/docs/{doc_id}/image-assets",
    response_model=DocumentImageAssetsReplaceResponse,
    summary="Replace document image assets extracted during ingestion",
)
async def replace_document_image_assets_internal(
    doc_id: str,
    payload: DocumentImageAssetsReplaceRequest,
    document_repo: DocumentRepository = Depends(get_document_repository),
    image_storage: DocumentImageAssetStorage = Depends(get_document_image_asset_storage),
    service: ServiceTokenContext = Depends(require_service_token),
) -> DocumentImageAssetsReplaceResponse:
    _ = service
    previous_assets = document_repo.list_document_image_assets(doc_id)
    try:
        saved = document_repo.replace_document_image_assets(
            doc_id=doc_id,
            job_id=payload.job_id,
            assets=[asset.model_dump() for asset in payload.assets],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "document_not_found", "message": str(exc)},
        ) from exc
    for asset in previous_assets:
        try:
            image_storage.delete(asset.object_path)
        except RuntimeError:
            continue
    document_repo.append_audit_event(
        event_type="internal.document_image_assets.replaced",
        actor_id=None,
        target_type="document",
        target_id=doc_id,
        payload={"job_id": payload.job_id, "asset_count": len(saved)},
    )
    return DocumentImageAssetsReplaceResponse(saved_count=len(saved))
