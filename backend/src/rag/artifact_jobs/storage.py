"""Storage contract for generated artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class StoredGeneratedArtifact:
    object_path: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class StoredGeneratedArtifactContent:
    content: bytes
    content_type: str
    filename: str


class GeneratedArtifactStorage(Protocol):
    def put(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        object_key: str | None = None,
    ) -> StoredGeneratedArtifact: ...

    def read(self, object_path: str) -> StoredGeneratedArtifactContent: ...

    def delete(self, object_path: str) -> bool: ...

    def list_objects(
        self,
        *,
        modified_before: datetime,
        limit: int = 100,
    ) -> list[str]: ...
