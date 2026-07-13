"""Map document domain records to public HTTP response schemas."""

from ...schemas.docs import (
    Document,
    DocumentClaim,
    DocumentCrossReference,
    DocumentEntity,
    DocumentSharesResponse,
    VersionNode,
)
from ..repository import DocumentRecord


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
        effective_date=document.effective_date.isoformat()
        if document.effective_date
        else None,
        expiry_date=document.expiry_date.isoformat() if document.expiry_date else None,
        description=document.description,
        summary=document.summary,
        language=document.language,
        topics=list(document.topics),
        llm_topics=list(document.llm_topics),
        metadata_version=_metadata_version(document.metadata_flags),
        metadata_confidence=_dict_metadata_field(
            document.metadata_flags,
            "metadata_confidence",
        ),
        metadata_provenance=_dict_metadata_field(
            document.metadata_flags,
            "metadata_provenance",
        ),
        auto_doc_type=document.auto_doc_type,
        extracted_dates=document.extracted_dates,
        metadata_flags=document.metadata_flags,
        entities=[_entity_to_schema(entity) for entity in entities or []],
        cross_references=[
            _cross_reference_to_schema(reference)
            for reference in cross_references or []
        ],
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
        effective_date=document.effective_date.isoformat()
        if document.effective_date
        else None,
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


def _cross_reference_to_schema(reference: object) -> DocumentCrossReference:
    return DocumentCrossReference(
        ref_text=str(getattr(reference, "ref_text")),
        ref_type=str(getattr(reference, "ref_type")),
        position=getattr(reference, "position"),
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
