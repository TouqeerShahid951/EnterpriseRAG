"""Document authorization helpers."""

from __future__ import annotations

from collections.abc import Sequence

from ..repositories.document_models import DocumentRecord
from ..repositories.identity import UserRecord
from ..shared.contracts.clearance import can_access_clearance
from .abac import normalize_group_path
from .permissions import can_read_document_metadata, can_write_document_scope, is_global_admin


def can_read_document(user: UserRecord, document: DocumentRecord) -> bool:
    if not can_read_document_metadata(user):
        return False
    if is_global_admin(user):
        return can_access_clearance(user.clearance_level, document.clearance_level)
    return can_read_group_path(user.group_paths, document.group_path) and can_access_clearance(
        user.clearance_level,
        document.clearance_level,
    )


def can_read_group_path(user_group_paths: Sequence[str], document_group_path: str) -> bool:
    doc_group = normalize_group_path(document_group_path)
    return any(normalize_group_path(group_path) == doc_group for group_path in user_group_paths)


def can_write_document(user: UserRecord, document: DocumentRecord) -> bool:
    return can_write_document_scope(user, document.group_path) and can_access_clearance(
        user.clearance_level,
        document.clearance_level,
    )
