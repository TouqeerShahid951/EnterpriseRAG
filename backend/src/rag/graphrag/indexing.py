"""Async GraphRAG indexing service."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import json
from time import perf_counter
from typing import Any, TypeVar

from .community_detector import CommunityDetector
from .community_summarizer import CommunitySummarizer
from .graph_extractor import GraphExtractor
from .models import (
    ChunkRecord,
    CommunitySummary,
    GraphClaim,
    GraphCommunity,
    GraphDocument,
    GraphEntity,
    GraphExtractionResult,
    GraphMention,
    GraphRelationship,
)
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
    extraction_concurrency: int = 1
    summary_concurrency: int = 1
    summarize_after_document: bool = True
    max_chunks_per_doc: int = 0
    min_chunk_chars: int = 80
    redis_url: str = ""
    extraction_checkpoint_ttl_seconds: int = 86400
    max_llm_community_summaries: int = 64


@dataclass(frozen=True)
class GraphRAGIndexResult:
    status: str
    doc_id: str
    partition_key: str | None = None
    chunks_indexed: int = 0
    communities_indexed: int = 0
    elapsed_ms: int = 0
    degraded_reason: str | None = None
    phase_timings_ms: dict[str, int] = field(default_factory=dict)


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
        self._checkpoint_client: object | None = None
        self._checkpoint_unavailable = False

    def index_document(
        self,
        doc_id: str,
        *,
        index_generation_id: str | None = None,
    ) -> GraphRAGIndexResult:
        started = perf_counter()
        timings = _PhaseTimings()
        if not self.config.enabled:
            return GraphRAGIndexResult(
                status="skipped",
                doc_id=doc_id,
                degraded_reason="graphrag_disabled",
                phase_timings_ms=timings.snapshot(),
            )
        try:
            with timings.measure("retrieve_chunks"):
                chunks = [
                    chunk
                    for chunk in self.qdrant.retrieve_document_chunks(
                        doc_id,
                        index_generation_id=index_generation_id,
                    )
                    if chunk.text.strip()
                ]
        except QdrantGraphRAGError as exc:
            return _result(
                "degraded",
                doc_id,
                started,
                degraded_reason=f"qdrant_unavailable: {str(exc)[:240]}",
                timings=timings,
            )
        if not chunks:
            return _result("skipped", doc_id, started, degraded_reason="no_document_chunks", timings=timings)
        with timings.measure("select_chunks"):
            chunks = self._select_chunks_for_graph(chunks)
        if not chunks:
            return _result("skipped", doc_id, started, degraded_reason="no_graph_candidate_chunks", timings=timings)

        # Documents should normally be single-partition, but group defensively to prevent ACL mixing.
        partitions: dict[str, list[ChunkRecord]] = {}
        for chunk in chunks:
            partitions.setdefault(chunk.partition_key, []).append(chunk)

        communities_indexed = 0
        selected_partition: str | None = None
        for partition, partition_chunks in partitions.items():
            selected_partition = partition
            result = self._index_partition_document(
                doc_id=doc_id,
                partition=partition,
                chunks=partition_chunks,
                timings=timings,
            )
            if result.degraded_reason:
                return _copy_result(result, elapsed_ms=_elapsed_ms(started), timings=timings)
            communities_indexed += result.communities_indexed
        return GraphRAGIndexResult(
            status="complete",
            doc_id=doc_id,
            partition_key=selected_partition,
            chunks_indexed=len(chunks),
            communities_indexed=communities_indexed,
            elapsed_ms=_elapsed_ms(started),
            phase_timings_ms=timings.snapshot(),
        )

    def rebuild_partition(self, partition: str, *, doc_id: str = "") -> GraphRAGIndexResult:
        started = perf_counter()
        timings = _PhaseTimings()
        if not self.config.enabled:
            return GraphRAGIndexResult(
                status="skipped",
                doc_id=doc_id,
                degraded_reason="graphrag_disabled",
                phase_timings_ms=timings.snapshot(),
            )
        try:
            with timings.measure("count_entities"):
                entity_count = self.store.count_entities_for_partition(partition)
        except Neo4jGraphStoreError as exc:
            return GraphRAGIndexResult(
                status="degraded",
                doc_id=doc_id,
                partition_key=partition,
                elapsed_ms=_elapsed_ms(started),
                degraded_reason=f"neo4j_unavailable: {str(exc)[:240]}",
                phase_timings_ms=timings.snapshot(),
            )
        if entity_count <= 0:
            try:
                with timings.measure("delete_neo4j_summaries"):
                    self.store.delete_partition_summaries(partition)
                with timings.measure("delete_qdrant_summaries"):
                    self.qdrant.delete_partition_summaries(partition)
            except Exception as exc:
                return GraphRAGIndexResult(
                    status="degraded",
                    doc_id=doc_id,
                    partition_key=partition,
                    elapsed_ms=_elapsed_ms(started),
                    degraded_reason=f"summary_cleanup_failed: {str(exc)[:240]}",
                    phase_timings_ms=timings.snapshot(),
                )
            return GraphRAGIndexResult(
                status="complete",
                doc_id=doc_id,
                partition_key=partition,
                communities_indexed=0,
                elapsed_ms=_elapsed_ms(started),
                phase_timings_ms=timings.snapshot(),
            )
        result = self._summarize_partition(doc_id=doc_id, partition=partition, timings=timings)
        return GraphRAGIndexResult(
            status=result.status,
            doc_id=doc_id,
            partition_key=partition,
            chunks_indexed=0,
            communities_indexed=result.communities_indexed,
            elapsed_ms=_elapsed_ms(started),
            degraded_reason=result.degraded_reason,
            phase_timings_ms=timings.snapshot(),
        )

    def _index_partition_document(
        self,
        *,
        doc_id: str,
        partition: str,
        chunks: list[ChunkRecord],
        timings: "_PhaseTimings",
    ) -> GraphRAGIndexResult:
        document = _document_from_chunks(doc_id, chunks)
        with timings.measure("extract_chunks"):
            extractions = self._extract_chunks(chunks)
        try:
            with timings.measure("replace_document_graph"):
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
                phase_timings_ms=timings.snapshot(),
            )

        if not self.config.summarize_after_document:
            return GraphRAGIndexResult(
                status="complete",
                doc_id=doc_id,
                partition_key=partition,
                chunks_indexed=len(chunks),
                communities_indexed=0,
                phase_timings_ms=timings.snapshot(),
            )

        return self._summarize_partition(
            doc_id=doc_id,
            partition=partition,
            chunks_indexed=len(chunks),
            timings=timings,
        )

    def _summarize_partition(
        self,
        *,
        doc_id: str,
        partition: str,
        chunks_indexed: int = 0,
        timings: "_PhaseTimings",
    ) -> GraphRAGIndexResult:
        with timings.measure("detect_communities"):
            detection = CommunityDetector(self.store).detect(partition)
        if detection.degraded_reason:
            return GraphRAGIndexResult(
                status="degraded",
                doc_id=doc_id,
                partition_key=partition,
                chunks_indexed=chunks_indexed,
                elapsed_ms=0,
                degraded_reason=detection.degraded_reason,
                phase_timings_ms=timings.snapshot(),
            )
        with timings.measure("summarize_communities"):
            summaries = self._summarize_communities(detection.communities)
        try:
            with timings.measure("replace_neo4j_summaries"):
                self.store.replace_partition_summaries(partition=partition, summaries=summaries)
            with timings.measure("embed_summaries"):
                vectors = self.inference.embed_many([_embedding_text(summary) for summary in summaries])
            with timings.measure("replace_qdrant_summaries"):
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
                chunks_indexed=chunks_indexed,
                communities_indexed=len(summaries),
                elapsed_ms=0,
                degraded_reason=f"summary_index_failed: {str(exc)[:240]}",
                phase_timings_ms=timings.snapshot(),
            )
        return GraphRAGIndexResult(
            status="complete",
            doc_id=doc_id,
            partition_key=partition,
            chunks_indexed=chunks_indexed,
            communities_indexed=len(summaries),
            phase_timings_ms=timings.snapshot(),
        )

    def _extract_chunks(self, chunks: list[ChunkRecord]) -> list[GraphExtractionResult]:
        extractor = GraphExtractor(self.inference)
        return _parallel_map(
            chunks,
            lambda chunk: self._extract_chunk_with_checkpoint(extractor, chunk),
            concurrency=self.config.extraction_concurrency,
            thread_name_prefix="graphrag-extract",
        )

    def _extract_chunk_with_checkpoint(self, extractor: GraphExtractor, chunk: ChunkRecord) -> GraphExtractionResult:
        cached = self._read_extraction_checkpoint(chunk)
        if cached is not None:
            return cached
        result = extractor.extract(chunk)
        self._write_extraction_checkpoint(chunk, result)
        return result

    def _read_extraction_checkpoint(self, chunk: ChunkRecord) -> GraphExtractionResult | None:
        client = self._checkpoint_redis()
        if client is None:
            return None
        try:
            raw = client.get(_checkpoint_key(chunk))  # type: ignore[attr-defined]
            if not raw:
                return None
            value = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            return _extraction_from_payload(json.loads(value))
        except Exception:
            return None

    def _write_extraction_checkpoint(self, chunk: ChunkRecord, result: GraphExtractionResult) -> None:
        client = self._checkpoint_redis()
        if client is None:
            return
        try:
            client.set(  # type: ignore[attr-defined]
                _checkpoint_key(chunk),
                json.dumps(asdict(result), ensure_ascii=True),
                ex=max(60, self.config.extraction_checkpoint_ttl_seconds),
            )
        except Exception:
            return

    def _checkpoint_redis(self) -> object | None:
        if not self.config.redis_url or self._checkpoint_unavailable:
            return None
        if self._checkpoint_client is not None:
            return self._checkpoint_client
        try:
            from redis import Redis

            self._checkpoint_client = Redis.from_url(self.config.redis_url, decode_responses=False)
        except Exception:
            self._checkpoint_unavailable = True
            return None
        return self._checkpoint_client

    def _summarize_communities(self, communities: list[GraphCommunity]) -> list[CommunitySummary]:
        llm_count = min(len(communities), self.config.max_llm_community_summaries)
        llm_summarizer = CommunitySummarizer(self.inference)
        llm_summaries = _parallel_map(
            communities[:llm_count],
            llm_summarizer.summarize,
            concurrency=self.config.summary_concurrency,
            thread_name_prefix="graphrag-summary",
        )
        fallback_summarizer = CommunitySummarizer()
        return llm_summaries + [
            fallback_summarizer.summarize(community)
            for community in communities[llm_count:]
        ]

    def _select_chunks_for_graph(self, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
        selected: list[ChunkRecord] = []
        seen_hashes: set[str] = set()
        for chunk in chunks:
            if not _is_graph_candidate(chunk, min_chars=self.config.min_chunk_chars):
                continue
            text_hash = chunk.text_hash or _normalized_text_hash(chunk.text)
            if text_hash in seen_hashes:
                continue
            seen_hashes.add(text_hash)
            selected.append(chunk)
        if self.config.max_chunks_per_doc <= 0 or len(selected) <= self.config.max_chunks_per_doc:
            return selected
        return sorted(selected, key=_chunk_priority, reverse=True)[: self.config.max_chunks_per_doc]


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
        extraction_concurrency=_bounded_mapping_int(value, "graphrag_extraction_concurrency", 1, minimum=1, maximum=32),
        summary_concurrency=_bounded_mapping_int(value, "graphrag_summary_concurrency", 1, minimum=1, maximum=16),
        summarize_after_document=bool(getattr(value, "graphrag_summarize_after_document", True)),
        max_chunks_per_doc=_bounded_mapping_int(value, "graphrag_max_chunks_per_doc", 0, minimum=0, maximum=10000),
        min_chunk_chars=_bounded_mapping_int(value, "graphrag_min_chunk_chars", 80, minimum=0, maximum=2000),
        redis_url=str(getattr(value, "redis_url", "")),
        extraction_checkpoint_ttl_seconds=_bounded_mapping_int(
            value,
            "graphrag_extraction_checkpoint_ttl_seconds",
            86400,
            minimum=60,
            maximum=604800,
        ),
        max_llm_community_summaries=_bounded_mapping_int(
            value,
            "graphrag_max_llm_community_summaries",
            64,
            minimum=0,
            maximum=10000,
        ),
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


def _result(
    status: str,
    doc_id: str,
    started: float,
    *,
    degraded_reason: str | None = None,
    timings: "_PhaseTimings | None" = None,
) -> GraphRAGIndexResult:
    return GraphRAGIndexResult(
        status=status,
        doc_id=doc_id,
        elapsed_ms=_elapsed_ms(started),
        degraded_reason=degraded_reason,
        phase_timings_ms=timings.snapshot() if timings is not None else {},
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((perf_counter() - started) * 1000))


_T = TypeVar("_T")
_U = TypeVar("_U")


class _PhaseTimings:
    def __init__(self) -> None:
        self._timings: dict[str, int] = {}

    @contextmanager
    def measure(self, phase: str):
        started = perf_counter()
        try:
            yield
        finally:
            self._timings[phase] = self._timings.get(phase, 0) + _elapsed_ms(started)

    def snapshot(self) -> dict[str, int]:
        return dict(self._timings)


def _parallel_map(
    items: list[_T],
    func: Callable[[_T], _U],
    *,
    concurrency: int,
    thread_name_prefix: str,
) -> list[_U]:
    if len(items) <= 1 or concurrency <= 1:
        return [func(item) for item in items]
    max_workers = min(len(items), max(1, concurrency))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix) as executor:
        return list(executor.map(func, items))


def _bounded_mapping_int(value: Any, attr: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(getattr(value, attr, default))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _copy_result(result: GraphRAGIndexResult, *, elapsed_ms: int, timings: _PhaseTimings) -> GraphRAGIndexResult:
    return GraphRAGIndexResult(
        status=result.status,
        doc_id=result.doc_id,
        partition_key=result.partition_key,
        chunks_indexed=result.chunks_indexed,
        communities_indexed=result.communities_indexed,
        elapsed_ms=elapsed_ms,
        degraded_reason=result.degraded_reason,
        phase_timings_ms=timings.snapshot(),
    )


def _is_graph_candidate(chunk: ChunkRecord, *, min_chars: int) -> bool:
    if chunk.claims or chunk.claim_ids or chunk.named_entities:
        return True
    chunk_type = chunk.chunk_type.lower()
    if chunk_type and chunk_type not in {"text", "paragraph"}:
        return True
    text = " ".join(chunk.text.split())
    if len(text) >= min_chars:
        return True
    return len(text.split()) >= 8


def _chunk_priority(chunk: ChunkRecord) -> tuple[int, int, int, int]:
    quality_penalty = len([flag for flag in chunk.quality_flags if "low" in flag.lower() or "ambiguous" in flag.lower()])
    return (
        10 if chunk.claims or chunk.claim_ids else 0,
        6 if chunk.named_entities else 0,
        max(0, 4 - quality_penalty),
        min(len(chunk.text), 2000),
    )


def _normalized_text_hash(text: str) -> str:
    from hashlib import sha256

    return sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()


def _checkpoint_key(chunk: ChunkRecord) -> str:
    text_hash = chunk.text_hash or _normalized_text_hash(chunk.text)
    return f"graphrag:extract:{chunk.doc_id}:{chunk.chunk_id}:{text_hash}"


def _extraction_from_payload(value: Any) -> GraphExtractionResult | None:
    if not isinstance(value, dict):
        return None
    try:
        return GraphExtractionResult(
            doc_id=str(value.get("doc_id") or ""),
            chunk_id=str(value.get("chunk_id") or ""),
            entities=[
                GraphEntity(**item)
                for item in value.get("entities", [])
                if isinstance(item, dict)
            ],
            mentions=[
                GraphMention(**item)
                for item in value.get("mentions", [])
                if isinstance(item, dict)
            ],
            relationships=[
                GraphRelationship(**item)
                for item in value.get("relationships", [])
                if isinstance(item, dict)
            ],
            claims=[
                GraphClaim(**item)
                for item in value.get("claims", [])
                if isinstance(item, dict)
            ],
        )
    except TypeError:
        return None
