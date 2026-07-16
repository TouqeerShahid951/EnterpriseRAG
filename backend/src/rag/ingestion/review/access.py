"""Authorization and item lookup helpers for ingestion review workflows."""

from fastapi import HTTPException, status

from rag.auth.document_access import can_write_document
from rag.auth.identity_models import UserRecord
from rag.documents.repository import DocumentRepository
from .models import HumanReviewRepository, ReviewItemRecord


def require_visible_pending_review_item(
    user: UserRecord,
    document_repo: DocumentRepository,
    review_repo: HumanReviewRepository,
    item_id: str,
) -> ReviewItemRecord:
    item = next(
        (
            item
            for item in review_repo.list_review_items(status="pending")
            if item.id == item_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "review_item_not_found",
                "message": "Review item was not found.",
            },
        )
    require_review_document_scope(user, document_repo, item.doc_id)
    return item


def require_visible_approvable_review_item(
    user: UserRecord,
    document_repo: DocumentRepository,
    review_repo: HumanReviewRepository,
    item_id: str,
) -> ReviewItemRecord:
    for item_status in ("pending", "approved"):
        item = next(
            (
                candidate
                for candidate in review_repo.list_review_items(status=item_status)
                if candidate.id == item_id
            ),
            None,
        )
        if item is not None:
            require_review_document_scope(user, document_repo, item.doc_id)
            return item
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "review_item_not_found",
            "message": "Review item was not found.",
        },
    )


def require_review_document_scope(
    user: UserRecord, document_repo: DocumentRepository, doc_id: str
) -> None:
    if not can_review_document(user, document_repo, doc_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "review_scope_forbidden",
                "message": "Review item is outside your Knowledge Space or clearance scope.",
            },
        )


def can_review_document(
    user: UserRecord, document_repo: DocumentRepository, doc_id: str
) -> bool:
    document = document_repo.get_document(doc_id)
    return document is not None and can_write_document(user, document)
