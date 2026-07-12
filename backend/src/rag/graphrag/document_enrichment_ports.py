"""Outbound queue port for user-requested document graph enrichment."""

from typing import Protocol


class DocumentEnrichmentQueue(Protocol):
    def enqueue(
        self,
        *,
        document_id: str,
        job_id: str,
        reason: str,
    ) -> None: ...
