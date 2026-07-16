"""Qdrant adapter for document access-scope updates."""

from __future__ import annotations

from ...query.http import ServiceRequestError
from ...query.qdrant import QdrantClient
from rag.documents.access_scope.ports import DocumentAccessScopeIndexError


class QdrantDocumentAccessScopeIndex:
    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    @property
    def collection_name(self) -> str:
        return self._client.collection

    def set_acl(self, document_id: str, access_group_paths: list[str]) -> None:
        try:
            self._client.set_document_acl_group_paths(
                document_id,
                acl_group_paths=access_group_paths,
            )
        except ServiceRequestError as exc:
            raise DocumentAccessScopeIndexError(str(exc)) from exc

    def set_access_scope(
        self,
        document_id: str,
        *,
        owner_group_path: str,
        access_group_paths: list[str],
    ) -> None:
        try:
            self._client.set_document_access_scope(
                document_id,
                group_path=owner_group_path,
                acl_group_paths=access_group_paths,
            )
        except ServiceRequestError as exc:
            raise DocumentAccessScopeIndexError(str(exc)) from exc
