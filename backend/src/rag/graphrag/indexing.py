"""Async GraphRAG indexing service."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from .community_detector import CommunityDetector
from .community_summarizer import CommunitySummarizer
from .graph_extractor import GraphExtractor
from .models import ChunkRecord, GraphDocument
from .neo4j_store import Neo4jConfig, Neo4jGraphStore, Neo4jGraphStoreError
from .qdrant import QdrantGraphRAGClient, QdrantGraphRAGError


@dataclass(frozen=True)
class GraphRAGRuntimeConfig:
    enabled: bool
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    qdrant_url: str
    qdrant_documents_collection: str
    qdrant_community_collection: str
    timeout_seconds: float = 45.0


@dataclass(frozen=True)
class GraphRAGIndexResult:
    status: str
    doc_id: str
    partition_key: str | None = None
    chunks_indexed: int = 0
    communities_indexed: int = 0
    elapsed_ms: int = 0
    degraded_reason: str | None = None


class GraphRAGIndexingService:
    def __init__(
        self,
        *,
        config: GraphRAGRuntimeConfig,
        inference: object,
        store: Neo4jGraphStore | None = None,
        qdrant: QdrantGraphRAGClient | None = None,
    ) -> None:
        self.config = config
        self.inference = inference
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

    def index_document(self, doc_id: str) -> GraphRAGIndexResult:
        started = perf_counter()
        if not self.config.enabled:
            return GraphRAGIndexResult(status="skipped", doc_id=doc_id, degraded_reason="graphrag_disabled")
        try:
            chunks = [chunk for chunk in self.qdrant.retrieve_document_chunks(doc_id) if chunk.text.strip()]
        except QdrantGraphRAGError as exc:
            return _result("degraded", doc_id, started, degraded_reason=f"qdrant_unavailable: {str(exc)[:240]}")
        if not chunks:
            return _result("skipped", doc_id, started, degraded_reason="no_document_chunks")

        # Documents should normally be single-partition, but group defensively to prevent ACL mixing.
        partitions: dict[str, list[ChunkRecord]] = {}
        for chunk in chunks:
            partitions.setdefault(chunk.partition_key, []).append(chunk)

        communities_indexed = 0
        selected_partition: str | None = None
        for partition, partition_chunks in partitions.items():
            selected_partition = partition
            result = self._index_partition_document(doc_id=doc_id, partition=partition, chunks=partition_chunks)
            if result.degraded_reason:
                return result
            communities_indexed += result.communities_indexed
        return GraphRAGIndexResult(
            status="complete",
            doc_id=doc_id,
            partition_key=selected_partition,
            chunks_indexed=len(chunks),
            communities_indexed=communities_indexed,
            elapsed_ms=_elapsed_ms(started),
        )

    def _index_partition_document(
        self,
        *,
        doc_id: str,
        partition: str,
        chunks: list[ChunkRecord],
    ) -> GraphRAGIndexResult:
        document = _document_from_chunks(doc_id, chunks)
        extractor = GraphExtractor(self.inference)
        extractions = [extractor.extract(chunk) for chunk in chunks]
        try:
            self.store.replace_document_extraction(
                document=document,
                chunks=chunks,
                extractions=extractions,
            )
        except Neo4jGraphStoreError as exc:
            return GraphRAGIndexResult(
                status="degraded",
                doc_id=doc_id,
                partition_key=partition,
                chunks_indexed=len(chunks),
                elapsed_ms=0,
                degraded_reason=f"neo4j_unavailable: {str(exc)[:240]}",
            )

        detection = CommunityDetector(self.store).detect(partition)
        if detection.degraded_reason:
            return GraphRAGIndexResult(
                status="degraded",
                doc_id=doc_id,
                partition_key=partition,
                chunks_indexed=len(chunks),
                elapsed_ms=0,
                degraded_reason=detection.degraded_reason,
            )
        summaries = [CommunitySummarizer(self.inference).summarize(community) for community in detection.communities]
        try:
            self.store.replace_partition_summaries(partition=partition, summaries=summaries)
            vectors = self.inference.embed_many([_embedding_text(summary) for summary in summaries])
            self.qdrant.replace_partition_summaries(
                partition_key=partition,
                summaries=summaries,
                vectors=vectors,
            )
        except Exception as exc:
            return GraphRAGIndexResult(
                status="degraded",
                doc_id=doc_id,
                partition_key=partition,
                chunks_indexed=len(chunks),
                communities_indexed=len(summaries),
                elapsed_ms=0,
                degraded_reason=f"summary_index_failed: {str(exc)[:240]}",
            )
        return GraphRAGIndexResult(
            status="complete",
            doc_id=doc_id,
            partition_key=partition,
            chunks_indexed=len(chunks),
            communities_indexed=len(summaries),
        )


def config_from_mapping(value: Any) -> GraphRAGRuntimeConfig:
    qdrant = getattr(value, "qdrant", None)
    qdrant_url = getattr(value, "qdrant_url", None) or getattr(qdrant, "url", None) or "http://qdrant:6333"
    documents_collection = (
        getattr(value, "qdrant_collection", None)
        or getattr(qdrant, "collection", None)
        or "documents"
    )
    return GraphRAGRuntimeConfig(
        enabled=bool(getattr(value, "graphrag_enabled")),
        neo4j_uri=str(getattr(value, "neo4j_uri")),
        neo4j_user=str(getattr(value, "neo4j_user")),
        neo4j_password=str(getattr(value, "neo4j_password")),
        neo4j_database=str(getattr(value, "neo4j_database")),
        qdrant_url=str(qdrant_url),
        qdrant_documents_collection=str(documents_collection),
        qdrant_community_collection=str(getattr(value, "graphrag_community_collection")),
        timeout_seconds=float(getattr(value, "rag_http_timeout_seconds", getattr(value, "http_timeout_seconds", 45.0))),
    )


def _document_from_chunks(doc_id: str, chunks: list[ChunkRecord]) -> GraphDocument:
    first = chunks[0]
    return GraphDocument(
        doc_id=doc_id,
        title=first.doc_title,
        group_path=first.group_path,
        clearance_level=first.clearance_level,
        clearance_rank=first.clearance_rank,
        is_current=first.is_current,
    )


def _embedding_text(summary) -> str:
    return "\n".join(
        part
        for part in (
            summary.title,
            summary.summary,
            "Entities: " + ", ".join(summary.important_entities) if summary.important_entities else "",
            "Relationships: " + "; ".join(summary.important_relationships) if summary.important_relationships else "",
        )
        if part
    )


def _result(status: str, doc_id: str, started: float, *, degraded_reason: str | None = None) -> GraphRAGIndexResult:
    return GraphRAGIndexResult(
        status=status,
        doc_id=doc_id,
        elapsed_ms=_elapsed_ms(started),
        degraded_reason=degraded_reason,
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))
