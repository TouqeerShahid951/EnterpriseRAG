from types import SimpleNamespace

from rag.graphrag.indexing import GraphRAGIndexingService, GraphRAGRuntimeConfig, config_from_mapping
from rag.graphrag.models import ChunkRecord, GraphCommunity, SourceRef


def _config(
    *,
    summarize_after_document: bool = True,
    max_chunks_per_doc: int = 0,
    min_chunk_chars: int = 80,
) -> GraphRAGRuntimeConfig:
    return GraphRAGRuntimeConfig(
        enabled=True,
        neo4j_uri="bolt://neo4j:7687",
        neo4j_user="neo4j",
        neo4j_password="pw",
        neo4j_database="neo4j",
        qdrant_url="http://qdrant:6333",
        qdrant_documents_collection="documents",
        qdrant_community_collection="graphrag_community_summaries",
        extraction_concurrency=2,
        summary_concurrency=2,
        summarize_after_document=summarize_after_document,
        max_chunks_per_doc=max_chunks_per_doc,
        min_chunk_chars=min_chunk_chars,
    )


class FakeStore:
    def replace_document_extraction(self, *, document, chunks, extractions) -> None:
        self.replaced_document = document
        self.replaced_chunks = chunks
        self.replaced_extractions = extractions

    def detect_communities_with_gds(self, partition: str) -> int:
        self.detected_partition = partition
        return 1

    def communities_for_partition(self, partition: str):
        return [
            GraphCommunity(
                id="community-1",
                partition_key=partition,
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
                level=0,
                entity_ids=["entity-1"],
                entity_names=["Acme Corp"],
                relationship_ids=[],
                source_refs=[SourceRef(doc_id="doc-1", chunk_id="chunk-1")],
                relationship_descriptions=[],
            )
        ]

    def replace_partition_summaries(self, *, partition: str, summaries) -> None:
        self.replaced_summaries = (partition, summaries)


class FakeQdrant:
    def retrieve_document_chunks(self, doc_id: str):
        return [
            ChunkRecord(
                doc_id=doc_id,
                chunk_id="chunk-1",
                text="Acme Corp met Project Apollo to review operational risk, deployment timing, and governance controls.",
                doc_title="Doc",
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
            ),
            ChunkRecord(
                doc_id=doc_id,
                chunk_id="chunk-2",
                text="Project Apollo briefed New York Office about logistics, reporting duties, and approval milestones.",
                doc_title="Doc",
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
            ),
        ]

    def replace_partition_summaries(self, *, partition_key: str, summaries, vectors) -> None:
        self.replaced_summaries = (partition_key, summaries, vectors)


class FakeCandidateQdrant:
    def retrieve_document_chunks(self, doc_id: str):
        return [
            ChunkRecord(
                doc_id=doc_id,
                chunk_id="chunk-1",
                text="Acme Corp met Project Apollo to discuss operational risk and deployment timing.",
                doc_title="Doc",
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
                text_hash="same-hash",
            ),
            ChunkRecord(
                doc_id=doc_id,
                chunk_id="chunk-duplicate",
                text="Acme Corp met Project Apollo to discuss operational risk and deployment timing.",
                doc_title="Doc",
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
                text_hash="same-hash",
            ),
            ChunkRecord(
                doc_id=doc_id,
                chunk_id="chunk-short",
                text="Hi.",
                doc_title="Doc",
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
            ),
            ChunkRecord(
                doc_id=doc_id,
                chunk_id="chunk-claim",
                text="Approved.",
                doc_title="Doc",
                group_path="/ops",
                clearance_level="NATO_RESTRICTED",
                clearance_rank=1,
                claims=[
                    {
                        "id": "claim-1",
                        "entity": "Acme Corp",
                        "attribute": "status",
                        "value": "Approved",
                    }
                ],
            ),
        ]


class FakeInference:
    def embed_many(self, texts):
        self.embedded_texts = texts
        return [[0.1, 0.2] for _text in texts]


class CountingInference(FakeInference):
    def __init__(self):
        self.generate_calls = 0

    def generate_json(self, **kwargs):
        self.generate_calls += 1
        return """
        {
          "entities": [{"name": "Acme Corp", "type": "organization", "confidence": 0.9}],
          "relationships": [],
          "claims": []
        }
        """


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str, **kwargs):
        self.values[key] = value
        return True


def test_config_from_mapping_reads_graphrag_concurrency() -> None:
    config = config_from_mapping(
        SimpleNamespace(
            graphrag_enabled=True,
            neo4j_uri="bolt://neo4j:7687",
            neo4j_user="neo4j",
            neo4j_password="pw",
            neo4j_database="neo4j",
            qdrant=SimpleNamespace(url="http://qdrant:6333", collection="documents"),
            graphrag_community_collection="graphrag_community_summaries",
            http_timeout_seconds=90,
            graphrag_extraction_concurrency=4,
            graphrag_summary_concurrency=3,
            graphrag_summarize_after_document=False,
            graphrag_max_chunks_per_doc=123,
            graphrag_min_chunk_chars=40,
            redis_url="redis://redis:6379/0",
            graphrag_extraction_checkpoint_ttl_seconds=120,
        )
    )

    assert config.extraction_concurrency == 4
    assert config.summary_concurrency == 3
    assert config.summarize_after_document is False
    assert config.max_chunks_per_doc == 123
    assert config.min_chunk_chars == 40
    assert config.redis_url == "redis://redis:6379/0"
    assert config.extraction_checkpoint_ttl_seconds == 120


def test_index_document_returns_phase_timings() -> None:
    result = GraphRAGIndexingService(
        config=_config(),
        inference=FakeInference(),
        store=FakeStore(),  # type: ignore[arg-type]
        qdrant=FakeQdrant(),  # type: ignore[arg-type]
    ).index_document("doc-1")

    assert result.status == "complete"
    assert result.chunks_indexed == 2
    assert result.communities_indexed == 1
    assert {
        "retrieve_chunks",
        "extract_chunks",
        "replace_document_graph",
        "detect_communities",
        "summarize_communities",
        "replace_neo4j_summaries",
        "embed_summaries",
        "replace_qdrant_summaries",
    }.issubset(result.phase_timings_ms)
    assert all(isinstance(value, int) and value >= 0 for value in result.phase_timings_ms.values())


def test_index_document_can_defer_partition_summary_rebuild() -> None:
    store = FakeStore()
    qdrant = FakeQdrant()

    result = GraphRAGIndexingService(
        config=_config(summarize_after_document=False),
        inference=FakeInference(),
        store=store,  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    ).index_document("doc-1")

    assert result.status == "complete"
    assert result.chunks_indexed == 2
    assert result.communities_indexed == 0
    assert result.partition_key == "/ops|clearance:1"
    assert "detect_communities" not in result.phase_timings_ms
    assert not hasattr(store, "detected_partition")
    assert not hasattr(qdrant, "replaced_summaries")


def test_index_document_dedupes_and_skips_low_signal_chunks() -> None:
    store = FakeStore()

    result = GraphRAGIndexingService(
        config=_config(summarize_after_document=False, min_chunk_chars=40),
        inference=FakeInference(),
        store=store,  # type: ignore[arg-type]
        qdrant=FakeCandidateQdrant(),  # type: ignore[arg-type]
    ).index_document("doc-1")

    assert result.status == "complete"
    assert result.chunks_indexed == 2
    assert [chunk.chunk_id for chunk in store.replaced_chunks] == ["chunk-1", "chunk-claim"]


def test_index_document_reuses_extraction_checkpoint() -> None:
    inference = CountingInference()
    service = GraphRAGIndexingService(
        config=GraphRAGRuntimeConfig(
            **{
                **_config(summarize_after_document=False).__dict__,
                "redis_url": "redis://redis:6379/0",
            }
        ),
        inference=inference,
        store=FakeStore(),  # type: ignore[arg-type]
        qdrant=FakeQdrant(),  # type: ignore[arg-type]
    )
    service._checkpoint_client = FakeRedis()

    first = service.index_document("doc-1")
    second = service.index_document("doc-1")

    assert first.status == "complete"
    assert second.status == "complete"
    assert inference.generate_calls == 2
