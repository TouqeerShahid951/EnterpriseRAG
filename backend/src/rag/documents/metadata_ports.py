"""Outbound index port for document metadata workflows."""

from __future__ import annotations

from typing import Protocol


class DocumentMetadataIndexError(RuntimeError):
    """The document index rejected a metadata update."""


class DocumentMetadataIndex(Protocol):
    @property
    def collection_name(self) -> str: ...

    def set_clearance(
        self,
        document_id: str,
        clearance_level: str,
    ) -> None: ...

    def set_topics(
        self,
        document_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
    ) -> None: ...
