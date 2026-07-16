"""Contracts for extracted document image asset storage."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredDocumentImageAsset:
    object_path: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class StoredDocumentImageAssetContent:
    content: bytes
    content_type: str
    filename: str


class DocumentImageAssetStorage(Protocol):
    def put(
        self,
        *,
        doc_id: str,
        asset_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredDocumentImageAsset: ...

    def read(self, object_path: str) -> StoredDocumentImageAssetContent: ...

    def delete(self, object_path: str) -> None: ...
