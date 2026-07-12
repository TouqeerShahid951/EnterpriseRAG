"""Outbound ports used by document access-scope workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import DocumentRecord


class DocumentAccessScopeIndexError(RuntimeError):
    """The document index rejected an access-scope update."""


class DocumentGraphCleanupError(RuntimeError):
    """Graph cleanup failed before an owner-transfer reindex."""


@dataclass(frozen=True)
class DocumentGraphCleanupResult:
    status: str
    partition_key: str | None


class DocumentAccessScopeIndex(Protocol):
    @property
    def collection_name(self) -> str: ...

    def set_acl(self, document_id: str, access_group_paths: list[str]) -> None: ...

    def set_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        access_group_paths: list[str],
    ) -> None: ...


class DocumentGraphStore(Protocol):
    def partition_key_for(self, document: DocumentRecord) -> str: ...

    def delete_document(
        self,
        *,
        document_id: str,
        partition_key: str,
    ) -> DocumentGraphCleanupResult: ...


class DocumentGraphIndexQueue(Protocol):
    def enqueue_document(
        self,
        *,
        document_id: str,
        job_id: str,
        reason: str,
    ) -> None: ...
