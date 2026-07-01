"""GraphRAG cleanup routines for document lifecycle changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rag.shared.contracts.clearance import clearance_rank

from .indexing import GraphRAGRuntimeConfig, config_from_mapping
from .neo4j_store import Neo4jConfig, Neo4jGraphStore, Neo4jGraphStoreError
from .qdrant import QdrantGraphRAGClient, QdrantGraphRAGError


class GraphRAGCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphRAGCleanupResult:
    status: str
    doc_id: str
    partition_key: str | None = None
    degraded_reason: str | None = None


class GraphRAGDeletionService:
    def __init__(
        self,
        *,
        config: GraphRAGRuntimeConfig,
        store: Neo4jGraphStore | None = None,
        qdrant: QdrantGraphRAGClient | None = None,
    ) -> None:
        self.config = config
        self.store = store or Neo4jGraphStore(
            config=Neo4jConfig(
                uri=config.neo4j_uri,
                user=config.neo4j_user,
                password=config.neo4j_password,
                database=config.neo4j_database,
            )
        )
        self.qdrant = qdrant or QdrantGraphRAGClient(
            base_url=config.qdrant_url,
            documents_collection=config.qdrant_documents_collection,
            community_collection=config.qdrant_community_collection,
            timeout_seconds=config.timeout_seconds,
        )

    def delete_document(self, *, doc_id: str, partition_key: str) -> GraphRAGCleanupResult:
        if not self.config.enabled:
            return GraphRAGCleanupResult(
                status="skipped",
                doc_id=doc_id,
                partition_key=partition_key,
                degraded_reason="graphrag_disabled",
            )
        try:
            self.store.delete_document_graph(doc_id)
            self.store.delete_partition_summaries(partition_key)
            self.qdrant.delete_partition_summaries(partition_key)
        except (Neo4jGraphStoreError, QdrantGraphRAGError) as exc:
            raise GraphRAGCleanupError(str(exc)) from exc
        return GraphRAGCleanupResult(status="complete", doc_id=doc_id, partition_key=partition_key)


def deletion_service_from_settings(settings: Any) -> GraphRAGDeletionService:
    return GraphRAGDeletionService(config=config_from_mapping(settings))


def partition_key_for_document(document: Any) -> str:
    return f"{document.group_path}|clearance:{clearance_rank(document.clearance_level)}"
