"""Storage contracts for uploaded document source files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredUpload:
    object_path: str
    size_bytes: int
    content_type: str | None


@dataclass(frozen=True)
class StoredUploadContent:
    content: bytes
    content_type: str | None
    filename: str


class UploadStorage(Protocol):
    def put(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> StoredUpload: ...

    def read(self, object_path: str) -> StoredUploadContent: ...

    def delete(self, object_path: str) -> None: ...
