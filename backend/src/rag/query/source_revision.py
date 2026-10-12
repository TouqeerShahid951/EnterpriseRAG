"""Recheck document authorization and revision before a cited answer leaves query."""

from rag.auth.context import UserContext
from rag.auth.identity_models import IdentityRepository
from rag.auth.document_access import can_read_document
from rag.documents.models import DocumentRepository
from rag.documents.source_revision import SourceRevision
from rag.shared.contracts.evidence import SourceAnchor


def sources_still_available(
    sources: list[SourceAnchor],
    *,
    user: UserContext,
    documents: DocumentRepository | None,
    identities: IdentityRepository | None = None,
) -> bool:
    if identities is not None:
        current = identities.get_user_by_id(user.user_id)
        if (
            current is None
            or not current.is_active
            or current.permission_version != user.permission_version
        ):
            return False
    for source in sources:
        if source.provenance_kind == "structured" and source.doc_id.startswith(
            ("connector-live-scope:", "managed-glossary:")
        ):
            continue
        if documents is None:
            return False
        document = documents.get_document(source.doc_id)
        if document is None or not can_read_document(user, document):
            return False
        if not SourceRevision(source.index_generation_id, source.content_hash).matches(
            document
        ):
            return False
    return True
