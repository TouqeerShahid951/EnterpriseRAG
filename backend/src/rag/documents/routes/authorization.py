"""Document HTTP authorization checks shared by document route groups."""

from fastapi import HTTPException, status

from ...auth.document_access import can_read_document, can_write_document
from ...auth.identity_models import UserRecord
from ..repository import DocumentRecord


def require_visible_document(
    user: UserRecord,
    document: DocumentRecord | None,
) -> DocumentRecord:
    if document is None or not can_read_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "document_not_found", "message": "Document was not found."},
        )
    return document


def require_writable_document(
    user: UserRecord,
    document: DocumentRecord | None,
) -> DocumentRecord:
    visible = require_visible_document(user, document)
    if not can_write_document(user, visible):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "document_forbidden",
                "message": "User cannot modify this document.",
            },
        )
    return visible
