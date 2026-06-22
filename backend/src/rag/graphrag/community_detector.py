"""Community detection orchestration for Neo4j GraphRAG."""

from __future__ import annotations

from dataclasses import dataclass

from .models import GraphCommunity
from .neo4j_store import Neo4jGraphStore, Neo4jGraphStoreError


@dataclass(frozen=True)
class CommunityDetectionResult:
    communities: list[GraphCommunity]
    community_count: int
    degraded_reason: str | None = None


class CommunityDetector:
    def __init__(self, store: Neo4jGraphStore) -> None:
        self.store = store

    def detect(self, partition_key: str) -> CommunityDetectionResult:
        try:
            count = self.store.detect_communities_with_gds(partition_key)
        except Neo4jGraphStoreError as exc:
            return CommunityDetectionResult(
                communities=[],
                community_count=0,
                degraded_reason=f"neo4j_gds_unavailable: {str(exc)[:240]}",
            )
        communities = self.store.communities_for_partition(partition_key)
        return CommunityDetectionResult(
            communities=communities,
            community_count=count or len(communities),
        )
