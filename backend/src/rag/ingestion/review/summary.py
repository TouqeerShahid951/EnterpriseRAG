"""Application behavior for the Review Queue navigation summary."""

from rag.auth.document_access import can_write_document
from rag.auth.identity_models import UserRecord
from rag.documents.repository import DocumentRepository

from .models import HumanReviewRepository, ImageReviewRepository


def count_visible_pending_review_documents(
    *,
    user: UserRecord,
    document_repo: DocumentRepository,
    human_review_repo: HumanReviewRepository,
    image_review_repo: ImageReviewRepository,
) -> int:
    """Count distinct pending-review documents the user can act on."""

    document_ids = {
        *human_review_repo.list_pending_human_review_document_ids(),
        *image_review_repo.list_pending_image_review_document_ids(),
    }
    documents = document_repo.list_documents_by_ids(tuple(document_ids))
    return sum(
        can_write_document(user, document)
        for document in documents
    )
