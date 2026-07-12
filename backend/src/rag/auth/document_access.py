"""Document authorization helpers."""

from __future__ import annotations

from collections.abc import Sequence

from ..repositories.document_models import DocumentRecord
from .identity_models import UserRecord
from ..shared.contracts.clearance import can_access_clearance
from .abac import normalize_group_path
from .permissions import can_manage_group_path, can_read_document_metadata, can_write_document_scope, is_global_admin


def can_read_document(user: UserRecord, document: DocumentRecord) -> bool:
    if not can_read_document_metadata(user):
        return False
    if is_global_admin(user):
        return can_access_clearance(user.clearance_level, document.clearance_level)
    return can_read_any_group_path(user.group_paths, document.access_group_paths) and can_access_clearance(
        user.clearance_level,
        document.clearance_level,
    )


def can_read_group_path(user_group_paths: Sequence[str], document_group_path: str) -> bool:
    doc_group = normalize_group_path(document_group_path)
    return any(normalize_group_path(group_path) == doc_group for group_path in user_group_paths)


def can_read_any_group_path(user_group_paths: Sequence[str], document_group_paths: Sequence[str]) -> bool:
    return any(can_read_group_path(user_group_paths, group_path) for group_path in document_group_paths)


def can_write_document(user: UserRecord, document: DocumentRecord) -> bool:
    if document.shared_group_paths and not is_global_admin(user):
        return False
    return can_write_document_scope(user, document.group_path) and can_access_clearance(
        user.clearance_level,
        document.clearance_level,
    )


def can_manage_document_ingestion(user: UserRecord, document: DocumentRecord) -> bool:
    if not can_read_document(user, document):
        return False
    return document.uploaded_by == user.id or can_manage_group_path(user, document.group_path)
