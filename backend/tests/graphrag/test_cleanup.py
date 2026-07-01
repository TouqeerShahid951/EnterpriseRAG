import pytest
from fastapi import HTTPException

from rag.api.routes import document_routes
from rag.api.routes.document_routes import _delete_document_graphrag, _enqueue_graphrag_partition_rebuild
from rag.graphrag.cleanup import GraphRAGCleanupError, GraphRAGDeletionService, partition_key_for_document
from rag.graphrag.indexing import GraphRAGRuntimeConfig
from rag.graphrag.indexing import GraphRAGIndexingService
from rag.graphrag.models import GraphCommunity, SourceRef
from rag.graphrag.neo4j_store import Neo4jGraphStoreError
from rag.graphrag.qdrant import QdrantGraphRAGError
from rag.services.graphrag_queue import GraphRAGPartitionRebuildMessage


def _config(enabled: bool = True) -> GraphRAGRuntimeConfig:
    return GraphRAGRuntimeConfig(
        enabled=enabled,
        neo4j_uri="bolt://neo4j:7687",
        neo4j_user="neo4j",
        neo4j_password="pw",
        neo4j_database="neo4j",
        qdrant_url="http://qdrant:6333",
        qdrant_documents_collection="documents",
        qdrant_community_collection="graphrag_community_summaries",
    )


class FakeStore:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.deleted_doc_ids: list[str] = []
        self.deleted_partitions: list[str] = []

    def delete_document_graph(self, doc_id: str) -> None:
        if self.error:
            raise self.error
        self.deleted_doc_ids.append(doc_id)

    def delete_partition_summaries(self, partition: str) -> None:
        self.deleted_partitions.append(partition)


class FakeQdrant:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.deleted_partitions: list[str] = []

    def delete_partition_summaries(self, partition_key: str) -> None:
        if self.error:
            raise self.error
        self.deleted_partitions.append(partition_key)


class FakeInference:
    def embed_many(self, texts):
        self.texts = texts
        return [[0.1, 0.2] for _text in texts]


class FakeRebuildStore:
    def __init__(self, entity_count: int):
        self.entity_count = entity_count
        self.deleted_partitions: list[str] = []
        self.replaced_summaries = None

    def count_entities_for_partition(self, partition: str) -> int:
        self.counted_partition = partition
        return self.entity_count

    def detect_communities_with_gds(self, partition: str) -> int:
        self.detected_partition = partition
        return 1

    def communities_for_partition(self, partition: str):
        return [
            GraphCommunity(
                id="community-1",
                partition_key=partition,
                group_path="/ops",
                clearance_level="NATO_CONFIDENTIAL",
                clearance_rank=2,
                level=0,
                entity_ids=["entity-1"],
                entity_names=["Operational Risk"],
                source_refs=[SourceRef(doc_id="doc-2", chunk_id="doc-2:0")],
            )
        ]

    def replace_partition_summaries(self, *, partition: str, summaries):
        self.replaced_summaries = (partition, summaries)

    def delete_partition_summaries(self, partition: str) -> None:
        self.deleted_partitions.append(partition)


class FakeRebuildQdrant:
    def __init__(self):
        self.deleted_partitions: list[str] = []
        self.replaced_summaries = None

    def delete_partition_summaries(self, partition_key: str) -> None:
        self.deleted_partitions.append(partition_key)

    def replace_partition_summaries(self, *, partition_key: str, summaries, vectors) -> None:
        self.replaced_summaries = (partition_key, summaries, vectors)


class FakeDocument:
    id = "doc-1"
    group_path = "/ops"
    clearance_level = "NATO_CONFIDENTIAL"


class FakeRepo:
    def __init__(self):
        self.events: list[dict[str, object]] = []

    def append_audit_event(self, **kwargs) -> None:
        self.events.append(kwargs)


class FailingRouteCleanup:
    def delete_document(self, *, doc_id: str, partition_key: str):
        raise GraphRAGCleanupError("neo4j unavailable")


class FakeRebuildQueue:
    def __init__(self, error: RuntimeError | None = None):
        self.error = error
        self.messages: list[GraphRAGPartitionRebuildMessage] = []

    def enqueue_partition_rebuild(self, message: GraphRAGPartitionRebuildMessage) -> None:
        if self.error:
            raise self.error
        self.messages.append(message)


def test_delete_document_cleans_neo4j_and_community_summaries() -> None:
    store = FakeStore()
    qdrant = FakeQdrant()

    result = GraphRAGDeletionService(
        config=_config(),
        store=store,  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    ).delete_document(doc_id="doc-1", partition_key="/ops|clearance:2")

    assert result.status == "complete"
    assert store.deleted_doc_ids == ["doc-1"]
    assert store.deleted_partitions == ["/ops|clearance:2"]
    assert qdrant.deleted_partitions == ["/ops|clearance:2"]


def test_disabled_graphrag_cleanup_is_skipped() -> None:
    store = FakeStore()
    qdrant = FakeQdrant()

    result = GraphRAGDeletionService(
        config=_config(enabled=False),
        store=store,  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    ).delete_document(doc_id="doc-1", partition_key="/ops|clearance:2")

    assert result.status == "skipped"
    assert result.degraded_reason == "graphrag_disabled"
    assert store.deleted_doc_ids == []
    assert qdrant.deleted_partitions == []


def test_cleanup_errors_are_wrapped() -> None:
    service = GraphRAGDeletionService(
        config=_config(),
        store=FakeStore(error=Neo4jGraphStoreError("neo4j unavailable")),  # type: ignore[arg-type]
        qdrant=FakeQdrant(),  # type: ignore[arg-type]
    )

    with pytest.raises(GraphRAGCleanupError, match="neo4j unavailable"):
        service.delete_document(doc_id="doc-1", partition_key="/ops|clearance:2")


def test_qdrant_cleanup_errors_are_wrapped() -> None:
    service = GraphRAGDeletionService(
        config=_config(),
        store=FakeStore(),  # type: ignore[arg-type]
        qdrant=FakeQdrant(error=QdrantGraphRAGError("qdrant unavailable")),  # type: ignore[arg-type]
    )

    with pytest.raises(GraphRAGCleanupError, match="qdrant unavailable"):
        service.delete_document(doc_id="doc-1", partition_key="/ops|clearance:2")


def test_partition_key_for_document_uses_group_and_clearance_rank() -> None:
    assert partition_key_for_document(FakeDocument()) == "/ops|clearance:2"


def test_route_cleanup_helper_records_audit_and_raises_502() -> None:
    repo = FakeRepo()

    with pytest.raises(HTTPException) as exc_info:
        _delete_document_graphrag(
            FakeDocument(),  # type: ignore[arg-type]
            event_type="documents.delete",
            actor_id="user-1",
            repo=repo,  # type: ignore[arg-type]
            graphrag=FailingRouteCleanup(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "document_graphrag_delete_failed"
    assert repo.events[0]["event_type"] == "documents.delete"
    assert repo.events[0]["payload"]["error_code"] == "document_graphrag_delete_failed"
    assert repo.events[0]["payload"]["graphrag_partition_key"] == "/ops|clearance:2"


def test_partition_rebuild_replaces_summaries_for_remaining_entities() -> None:
    store = FakeRebuildStore(entity_count=1)
    qdrant = FakeRebuildQdrant()
    inference = FakeInference()

    result = GraphRAGIndexingService(
        config=_config(),
        inference=inference,
        store=store,  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    ).rebuild_partition("/ops|clearance:2", doc_id="doc-1")

    assert result.status == "complete"
    assert result.communities_indexed == 1
    assert store.replaced_summaries[0] == "/ops|clearance:2"
    assert qdrant.replaced_summaries[0] == "/ops|clearance:2"
    assert qdrant.replaced_summaries[2] == [[0.1, 0.2]]


def test_partition_rebuild_clears_empty_partition() -> None:
    store = FakeRebuildStore(entity_count=0)
    qdrant = FakeRebuildQdrant()

    result = GraphRAGIndexingService(
        config=_config(),
        inference=FakeInference(),
        store=store,  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    ).rebuild_partition("/ops|clearance:2", doc_id="doc-1")

    assert result.status == "complete"
    assert result.communities_indexed == 0
    assert store.deleted_partitions == ["/ops|clearance:2"]
    assert qdrant.deleted_partitions == ["/ops|clearance:2"]


def test_route_enqueue_helper_queues_partition_rebuild(monkeypatch) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    queue = FakeRebuildQueue()

    status = _enqueue_graphrag_partition_rebuild(
        FakeDocument(),  # type: ignore[arg-type]
        event_type="documents.delete",
        actor_id="user-1",
        repo=FakeRepo(),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        partition_key="/ops|clearance:2",
    )

    assert status == "queued"
    assert queue.messages == [
        GraphRAGPartitionRebuildMessage(
            doc_id="doc-1",
            partition_key="/ops|clearance:2",
            reason="documents.delete",
        )
    ]


def test_route_enqueue_helper_records_warning_on_enqueue_failure(monkeypatch) -> None:
    monkeypatch.setattr(document_routes.settings, "graphrag_enabled", True)
    repo = FakeRepo()

    status = _enqueue_graphrag_partition_rebuild(
        FakeDocument(),  # type: ignore[arg-type]
        event_type="documents.delete",
        actor_id="user-1",
        repo=repo,  # type: ignore[arg-type]
        queue=FakeRebuildQueue(error=RuntimeError("redis unavailable")),  # type: ignore[arg-type]
        partition_key="/ops|clearance:2",
    )

    assert status == "enqueue_failed"
    assert repo.events[0]["payload"]["warning_code"] == "graphrag_rebuild_enqueue_failed"
