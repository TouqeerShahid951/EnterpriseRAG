"""Transport-neutral errors raised by folder-ingestion use cases."""

from __future__ import annotations

from typing import Literal


FolderIngestionErrorCategory = Literal[
    "invalid",
    "forbidden",
    "not_found",
    "too_large",
    "unavailable",
]


class FolderIngestionRejected(RuntimeError):
    """A safe, expected rejection that an entrypoint can map to its protocol."""

    def __init__(
        self,
        *,
        category: FolderIngestionErrorCategory,
        code: str,
        message: str,
    ) -> None:
        self.category = category
        self.code = code
        self.message = message
        super().__init__(message)
