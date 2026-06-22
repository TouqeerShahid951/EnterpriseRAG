"""Shared GraphRAG data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5


def stable_id(*parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(str(part) for part in parts)))


def normalized_name(value: str) -> str:
    return " ".join(value.lower().split())


def partition_key(*, group_path: str, clearance_rank: int) -> str:
    return f"{group_path}|clearance:{clearance_rank}"


@dataclass(frozen=True)
class SourceRef:
    doc_id: str
    chunk_id: str


@dataclass(frozen=True)
class GraphEntity:
    id: str
    name: str
    type: str = "unknown"
    normalized_name: str = ""
    confidence: float = 0.0

    @classmethod
    def from_name(
        cls,
        *,
        name: str,
        entity_type: str,
        partition: str,
        confidence: float = 0.0,
    ) -> "GraphEntity":
        normalized = normalized_name(name)
        normalized_type = normalized_name(entity_type or "unknown") or "unknown"
        return cls(
            id=stable_id("graph-entity", partition, normalized_type, normalized),
            name=name.strip(),
            type=normalized_type,
            normalized_name=normalized,
            confidence=_bounded_confidence(confidence),
        )


@dataclass(frozen=True)
class GraphMention:
    id: str
    entity_id: str
    entity_name: str
    doc_id: str
    chunk_id: str
    evidence_text: str
    confidence: float = 0.0


@dataclass(frozen=True)
class GraphRelationship:
    id: str
    source_entity_id: str
    target_entity_id: str
    source_name: str
    target_name: str
    type: str
    description: str
    doc_id: str
    chunk_id: str
    evidence_text: str
    confidence: float = 0.0
    weight: float = 1.0


@dataclass(frozen=True)
class GraphClaim:
    id: str
    entity_id: str
    entity_name: str
    claim: str
    doc_id: str
    chunk_id: str
    evidence_text: str
    confidence: float = 0.0


@dataclass(frozen=True)
class GraphExtractionResult:
    doc_id: str
    chunk_id: str
    entities: list[GraphEntity] = field(default_factory=list)
    mentions: list[GraphMention] = field(default_factory=list)
    relationships: list[GraphRelationship] = field(default_factory=list)
    claims: list[GraphClaim] = field(default_factory=list)


@dataclass(frozen=True)
class ChunkRecord:
    doc_id: str
    chunk_id: str
    text: str
    doc_title: str
    group_path: str
    clearance_level: str
    clearance_rank: int
    is_current: bool = True
    page: int | None = None
    page_start: int | None = None
    page_end: int | None = None

    @property
    def partition_key(self) -> str:
        return partition_key(group_path=self.group_path, clearance_rank=self.clearance_rank)


@dataclass(frozen=True)
class GraphDocument:
    doc_id: str
    title: str
    group_path: str
    clearance_level: str
    clearance_rank: int
    is_current: bool = True

    @property
    def partition_key(self) -> str:
        return partition_key(group_path=self.group_path, clearance_rank=self.clearance_rank)


@dataclass(frozen=True)
class GraphCommunity:
    id: str
    partition_key: str
    group_path: str
    clearance_level: str
    clearance_rank: int
    level: int
    entity_ids: list[str] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    source_refs: list[SourceRef] = field(default_factory=list)
    relationship_descriptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CommunitySummary:
    id: str
    community_id: str
    partition_key: str
    group_path: str
    clearance_level: str
    clearance_rank: int
    level: int
    title: str
    summary: str
    important_entities: list[str] = field(default_factory=list)
    important_relationships: list[str] = field(default_factory=list)
    source_refs: list[SourceRef] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PartialAnswer:
    text: str
    community_id: str
    supporting_entities: list[str]
    source_refs: list[SourceRef]
    relevance_score: float = 0.0


def _bounded_confidence(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
