from dataclasses import dataclass
from time import perf_counter

from rag.auth.context import UserContext
from rag.graphrag.graphrag_retriever import GraphRAGRetriever
from rag.graphrag.models import CommunitySummary, SourceRef
from rag.graphrag.qdrant import CommunitySearchHit
from rag.query.qdrant import SearchHit
from rag.query.routing.routing_models import RoutePlan
from rag.query.state import initial_state
from rag.query.schemas import QueryRequest


@dataclass
class FakeConfig:
    graphrag_enabled: bool = True
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "documents"
    graphrag_community_collection: str = "graphrag_community_summaries"
    rag_http_timeout_seconds: float = 45.0


class FakeEmbedder:
    def embed(self, text):
        self.text = text
        return [0.1, 0.2]


class FakeCommunityQdrant:
    def __init__(self):
        self.filter = None

    def search_summaries(self, *, vector, qdrant_filter, limit):
        self.filter = qdrant_filter
        summary = CommunitySummary(
            id="summary-1",
            community_id="community-1",
            partition_key="/ops|clearance:2",
            group_path="/ops",
            clearance_level="NATO_CONFIDENTIAL",
            clearance_rank=2,
            level=0,
            title="Recurring risk pattern",
            summary="A recurring risk appears across the source chunks.",
            source_refs=[SourceRef(doc_id="doc-a", chunk_id="chunk-a")],
        )
        return [CommunitySearchHit(id="point-1", score=0.9, summary=summary)]


class FakeDocumentQdrant:
    def __init__(self):
        self.chunk_refs = None
        self.filter = None

    def retrieve_chunks(self, chunk_refs, *, qdrant_filter, cancellation_token=None):
        self.chunk_refs = chunk_refs
        self.filter = qdrant_filter
        return [
            SearchHit(
                point_id="point-doc-a",
                score=1.0,
                payload={
                    "doc_id": "doc-a",
                    "chunk_id": "chunk-a",
                    "doc_title": "Risk Report",
                    "text": "Risk evidence.",
                    "group_path": "/ops",
                    "clearance_level": "NATO_CONFIDENTIAL",
                    "clearance_rank": 2,
                    "is_current": True,
                },
            )
        ]


def test_graphrag_retriever_applies_abac_and_document_scope() -> None:
    community_qdrant = FakeCommunityQdrant()
    document_qdrant = FakeDocumentQdrant()
    ctx = initial_state(
        trace_id="trace-1",
        session_id="session-1",
        request=QueryRequest(
            query="What are the recurring risks?",
            group_path="/ops",
            document_ids=["doc-a"],
        ),
        user=UserContext(
            user_id="user-1",
            email="user@example.com",
            group_paths=("/ops", "/finance"),
            clearance_level="NATO_SECRET",
            permission_version=1,
        ),
        started=perf_counter(),
    )
    ctx["route_plan"] = RoutePlan(
        original_query=ctx["request"].query,
        resolved_query=ctx["request"].query,
        intent="graphrag_global",
        retrieval_strategy="graphrag_global",
        public_intent="aggregation",
    )

    result = GraphRAGRetriever(
        config=FakeConfig(),
        embedder=FakeEmbedder(),
        document_qdrant=document_qdrant,  # type: ignore[arg-type]
        community_qdrant=community_qdrant,  # type: ignore[arg-type]
    ).retrieve(ctx)

    assert result.is_available is True
    assert document_qdrant.chunk_refs == [("doc-a", "chunk-a")]
    assert _has_condition(community_qdrant.filter, "group_path", "/ops")
    assert _has_range(community_qdrant.filter, "clearance_rank", "lte", 3)
    assert _has_condition(community_qdrant.filter, "is_current", True)
    assert _has_condition(community_qdrant.filter, "source_doc_ids", "doc-a")
    assert _has_condition(document_qdrant.filter, "group_path", "/ops")
    assert _has_range(document_qdrant.filter, "clearance_rank", "lte", 3)
    assert _has_condition(document_qdrant.filter, "doc_id", "doc-a")


def test_disabled_graphrag_returns_degraded_result() -> None:
    ctx = initial_state(
        trace_id="trace-1",
        session_id="session-1",
        request=QueryRequest(query="major themes"),
        user=UserContext(
            user_id="user-1",
            email="user@example.com",
            group_paths=("/ops",),
            clearance_level="NATO_SECRET",
        ),
        started=perf_counter(),
    )

    result = GraphRAGRetriever(
        config=FakeConfig(graphrag_enabled=False),
        embedder=FakeEmbedder(),
        document_qdrant=FakeDocumentQdrant(),  # type: ignore[arg-type]
        community_qdrant=FakeCommunityQdrant(),  # type: ignore[arg-type]
    ).retrieve(ctx)

    assert result.is_available is False
    assert result.degraded_reason == "graphrag_disabled"


def _has_condition(qdrant_filter, key: str, value) -> bool:
    if isinstance(qdrant_filter, dict):
        if qdrant_filter.get("key") == key and qdrant_filter.get("match", {}).get("value") == value:
            return True
        return any(_has_condition(item, key, value) for item in _children(qdrant_filter))
    if isinstance(qdrant_filter, list):
        return any(_has_condition(item, key, value) for item in qdrant_filter)
    return False


def _has_range(qdrant_filter, key: str, operator: str, value) -> bool:
    if isinstance(qdrant_filter, dict):
        if qdrant_filter.get("key") == key and qdrant_filter.get("range", {}).get(operator) == value:
            return True
        return any(_has_range(item, key, operator, value) for item in _children(qdrant_filter))
    if isinstance(qdrant_filter, list):
        return any(_has_range(item, key, operator, value) for item in qdrant_filter)
    return False


def _children(value: dict):
    for key in ("must", "should", "must_not"):
        child = value.get(key)
        if isinstance(child, list):
            yield from child
