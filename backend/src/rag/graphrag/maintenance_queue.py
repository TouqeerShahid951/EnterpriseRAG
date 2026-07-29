"""Public contract for scheduling and cancelling GraphRAG maintenance work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GraphRAGDocumentIndexMessage:
    doc_id: str
    job_id: str
    reason: str
    index_generation_id: str | None = None


@dataclass(frozen=True)
class GraphRAGPartitionRebuildMessage:
    doc_id: str
    partition_key: str
    reason: str


class GraphRAGMaintenanceQueue(Protocol):
    def cancel(self, task_id: str, *, terminate: bool = False) -> None: ...
    def enqueue_document_index(self, message: GraphRAGDocumentIndexMessage) -> None: ...
    def enqueue_partition_rebuild(
        self,
        message: GraphRAGPartitionRebuildMessage,
    ) -> None: ...
