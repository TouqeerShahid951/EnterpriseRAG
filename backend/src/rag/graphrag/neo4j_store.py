"""Neo4j graph store adapter for GraphRAG."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .models import (
    ChunkRecord,
    CommunitySummary,
    GraphCommunity,
    GraphDocument,
    GraphExtractionResult,
    SourceRef,
    stable_id,
)


class Neo4jGraphStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str = "neo4j"


class Neo4jGraphStore:
    def __init__(self, *, config: Neo4jConfig, driver: object | None = None) -> None:
        self.config = config
        self._driver = driver

    @property
    def driver(self):
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise Neo4jGraphStoreError("neo4j Python driver is not installed") from exc
            self._driver = GraphDatabase.driver(
                self.config.uri,
                auth=(self.config.user, self.config.password),
            )
        return self._driver

    def close(self) -> None:
        close = getattr(self._driver, "close", None)
        if callable(close):
            close()

    def ensure_schema(self) -> None:
        for query in _SCHEMA_QUERIES:
            self._run(query)

    def replace_document_extraction(
        self,
        *,
        document: GraphDocument,
        chunks: list[ChunkRecord],
        extractions: list[GraphExtractionResult],
    ) -> None:
        self.ensure_schema()
        self._delete_document_graph(document.doc_id)
        self._run(
            """
            MERGE (doc:Document {id: $id})
            SET doc.title = $title,
                doc.group_path = $group_path,
                doc.clearance_level = $clearance_level,
                doc.clearance_rank = $clearance_rank,
                doc.partition_key = $partition_key,
                doc.is_current = $is_current,
                doc.updated_at = datetime()
            """,
            _document_params(document),
        )
        self._upsert_chunks(chunks)
        self._upsert_entities(extractions, partition=document.partition_key)
        self._upsert_mentions(extractions, partition=document.partition_key)
        self._upsert_relationships(extractions, partition=document.partition_key)
        self._upsert_claims(extractions, partition=document.partition_key)

    def detect_communities_with_gds(self, partition: str) -> int:
        graph_name = _gds_graph_name(partition)
        self._run("CALL gds.graph.drop($graph_name, false) YIELD graphName RETURN graphName", {"graph_name": graph_name})
        self._run(
            """
            MATCH (source:GraphEntity {partition_key: $partition_key})
            OPTIONAL MATCH (source)-[rel:RELATES_TO]->(target:GraphEntity {partition_key: $partition_key})
            WITH gds.graph.project(
              $graph_name,
              source,
              target,
              {
                relationshipType: 'RELATES_TO',
                relationshipProperties: CASE WHEN rel IS NULL THEN {} ELSE rel { .weight } END
              },
              {undirectedRelationshipTypes: ['*']}
            ) AS graph
            RETURN graph.graphName AS graphName
            """,
            {"graph_name": graph_name, "partition_key": partition},
        )
        rows = self._run(
            """
            CALL gds.leiden.write($graph_name, {
              writeProperty: 'community_id',
              relationshipWeightProperty: 'weight'
            })
            YIELD communityCount
            RETURN communityCount
            """,
            {"graph_name": graph_name},
        )
        self._run("CALL gds.graph.drop($graph_name, false) YIELD graphName RETURN graphName", {"graph_name": graph_name})
        if not rows:
            return 0
        return int(rows[0].get("communityCount") or 0)

    def communities_for_partition(self, partition: str) -> list[GraphCommunity]:
        rows = self._run(
            """
            MATCH (entity:GraphEntity {partition_key: $partition_key})
            WHERE entity.community_id IS NOT NULL
            WITH entity.community_id AS community_id, collect(entity) AS entities
            OPTIONAL MATCH (left:GraphEntity {partition_key: $partition_key})-[rel:RELATES_TO]->(right:GraphEntity {partition_key: $partition_key})
            WHERE left.community_id = community_id AND right.community_id = community_id
            WITH community_id, entities, collect(rel) AS rels
            OPTIONAL MATCH (mention_entity:GraphEntity {partition_key: $partition_key})-[mention:MENTIONED_IN]->(chunk:Chunk)
            WHERE mention_entity.community_id = community_id
            WITH community_id, entities, rels, collect(DISTINCT {doc_id: chunk.doc_id, chunk_id: chunk.id}) AS refs
            RETURN community_id,
                   [entity IN entities | entity.id] AS entity_ids,
                   [entity IN entities | entity.name] AS entity_names,
                   [rel IN rels | rel.id] AS relationship_ids,
                   [rel IN rels | rel.description] AS relationship_descriptions,
                   refs
            ORDER BY size(entity_ids) DESC, community_id
            """,
            {"partition_key": partition},
        )
        communities: list[GraphCommunity] = []
        for row in rows:
            refs = [
                SourceRef(doc_id=str(item.get("doc_id")), chunk_id=str(item.get("chunk_id")))
                for item in row.get("refs", [])
                if isinstance(item, dict) and item.get("doc_id") and item.get("chunk_id")
            ]
            entity_names = [str(item) for item in row.get("entity_names", []) if str(item).strip()]
            relationship_descriptions = [
                str(item) for item in row.get("relationship_descriptions", []) if str(item).strip()
            ]
            community_id = stable_id("graph-community", partition, row.get("community_id"))
            group_path, clearance_rank = _partition_parts(partition)
            communities.append(
                GraphCommunity(
                    id=community_id,
                    partition_key=partition,
                    group_path=group_path,
                    clearance_level=_clearance_from_rank(clearance_rank),
                    clearance_rank=clearance_rank,
                    level=0,
                    entity_ids=[str(item) for item in row.get("entity_ids", [])],
                    entity_names=entity_names,
                    relationship_ids=[str(item) for item in row.get("relationship_ids", [])],
                    source_refs=_dedupe_refs(refs),
                    relationship_descriptions=relationship_descriptions,
                )
            )
        return communities

    def replace_partition_summaries(self, *, partition: str, summaries: list[CommunitySummary]) -> None:
        self._run(
            """
            MATCH (summary:CommunitySummary {partition_key: $partition_key})
            DETACH DELETE summary
            """,
            {"partition_key": partition},
        )
        self._run(
            """
            MATCH (community:Community {partition_key: $partition_key})
            DETACH DELETE community
            """,
            {"partition_key": partition},
        )
        for summary in summaries:
            self._run(
                """
                MERGE (community:Community {id: $community_id})
                SET community.partition_key = $partition_key,
                    community.group_path = $group_path,
                    community.clearance_level = $clearance_level,
                    community.clearance_rank = $clearance_rank,
                    community.level = $level,
                    community.updated_at = datetime()
                MERGE (summary:CommunitySummary {id: $summary_id})
                SET summary.community_id = $community_id,
                    summary.partition_key = $partition_key,
                    summary.group_path = $group_path,
                    summary.clearance_level = $clearance_level,
                    summary.clearance_rank = $clearance_rank,
                    summary.level = $level,
                    summary.title = $title,
                    summary.summary = $summary,
                    summary.important_entities = $important_entities,
                    summary.important_relationships = $important_relationships,
                    summary.source_doc_ids = $source_doc_ids,
                    summary.source_chunk_ids = $source_chunk_ids,
                    summary.source_refs_json = $source_refs_json,
                    summary.updated_at = datetime()
                MERGE (community)-[:HAS_SUMMARY]->(summary)
                WITH community
                MATCH (entity:GraphEntity {partition_key: $partition_key})
                WHERE entity.id IN $entity_ids
                MERGE (entity)-[:IN_COMMUNITY]->(community)
                """,
                {
                    "community_id": summary.community_id,
                    "summary_id": summary.id,
                    "partition_key": summary.partition_key,
                    "group_path": summary.group_path,
                    "clearance_level": summary.clearance_level,
                    "clearance_rank": summary.clearance_rank,
                    "level": summary.level,
                    "title": summary.title,
                    "summary": summary.summary,
                    "important_entities": summary.important_entities,
                    "important_relationships": summary.important_relationships,
                    "source_doc_ids": sorted({ref.doc_id for ref in summary.source_refs}),
                    "source_chunk_ids": sorted({ref.chunk_id for ref in summary.source_refs}),
                    "source_refs_json": json.dumps(
                        [{"doc_id": ref.doc_id, "chunk_id": ref.chunk_id} for ref in summary.source_refs],
                        ensure_ascii=True,
                    ),
                    "entity_ids": summary.entity_ids,
                },
            )

    def _delete_document_graph(self, doc_id: str) -> None:
        self._run(
            """
            MATCH (doc:Document {id: $doc_id})
            OPTIONAL MATCH (doc)<-[:BELONGS_TO]-(chunk:Chunk)
            OPTIONAL MATCH (entity:GraphEntity)-[mention:MENTIONED_IN]->(chunk)
            DELETE mention
            WITH doc, collect(chunk) AS chunks
            OPTIONAL MATCH ()-[rel:RELATES_TO {doc_id: $doc_id}]->()
            DELETE rel
            WITH doc, chunks
            OPTIONAL MATCH (claim:GraphClaim {doc_id: $doc_id})
            DETACH DELETE claim
            WITH doc, chunks
            FOREACH (chunk IN chunks | DETACH DELETE chunk)
            DETACH DELETE doc
            """,
            {"doc_id": doc_id},
        )

    def _upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        rows = [_chunk_params(chunk) for chunk in chunks]
        self._run(
            """
            UNWIND $rows AS row
            MATCH (doc:Document {id: row.doc_id})
            MERGE (chunk:Chunk {id: row.chunk_id})
            SET chunk.doc_id = row.doc_id,
                chunk.text = row.text,
                chunk.group_path = row.group_path,
                chunk.clearance_level = row.clearance_level,
                chunk.clearance_rank = row.clearance_rank,
                chunk.partition_key = row.partition_key,
                chunk.is_current = row.is_current,
                chunk.page = row.page,
                chunk.page_start = row.page_start,
                chunk.page_end = row.page_end,
                chunk.updated_at = datetime()
            MERGE (chunk)-[:BELONGS_TO]->(doc)
            """,
            {"rows": rows},
        )

    def _upsert_entities(self, extractions: list[GraphExtractionResult], *, partition: str) -> None:
        group_path, clearance_rank = _partition_parts(partition)
        clearance_level = _clearance_from_rank(clearance_rank)
        entities: dict[str, dict[str, Any]] = {}
        for extraction in extractions:
            for entity in extraction.entities:
                row = entities.setdefault(
                    entity.id,
                    {
                        "id": entity.id,
                        "name": entity.name,
                        "type": entity.type,
                        "normalized_name": entity.normalized_name,
                        "confidence": entity.confidence,
                        "partition_key": partition,
                        "group_path": group_path,
                        "clearance_level": clearance_level,
                        "clearance_rank": clearance_rank,
                        "source_doc_ids": set(),
                        "source_chunk_ids": set(),
                        "is_current": True,
                    },
                )
                row["confidence"] = max(float(row["confidence"]), entity.confidence)
                row["source_doc_ids"].add(extraction.doc_id)
                row["source_chunk_ids"].add(extraction.chunk_id)
        rows = [
            {
                **row,
                "source_doc_ids": sorted(row["source_doc_ids"]),
                "source_chunk_ids": sorted(row["source_chunk_ids"]),
            }
            for row in entities.values()
        ]
        self._run(
            """
            UNWIND $rows AS row
            MERGE (entity:GraphEntity {id: row.id})
            SET entity.name = row.name,
                entity.type = row.type,
                entity.normalized_name = row.normalized_name,
                entity.confidence = row.confidence,
                entity.partition_key = row.partition_key,
                entity.group_path = row.group_path,
                entity.clearance_level = row.clearance_level,
                entity.clearance_rank = row.clearance_rank,
                entity.source_doc_ids = row.source_doc_ids,
                entity.source_chunk_ids = row.source_chunk_ids,
                entity.is_current = row.is_current,
                entity.updated_at = datetime()
            """,
            {"rows": rows},
        )

    def _upsert_mentions(self, extractions: list[GraphExtractionResult], *, partition: str) -> None:
        group_path, clearance_rank = _partition_parts(partition)
        clearance_level = _clearance_from_rank(clearance_rank)
        rows = [
            {
                "id": mention.id,
                "entity_id": mention.entity_id,
                "chunk_id": mention.chunk_id,
                "doc_id": mention.doc_id,
                "evidence_text": mention.evidence_text,
                "confidence": mention.confidence,
                "partition_key": partition,
                "group_path": group_path,
                "clearance_level": clearance_level,
                "clearance_rank": clearance_rank,
                "is_current": True,
            }
            for extraction in extractions
            for mention in extraction.mentions
        ]
        self._run(
            """
            UNWIND $rows AS row
            MATCH (entity:GraphEntity {id: row.entity_id})
            MATCH (chunk:Chunk {id: row.chunk_id})
            MERGE (entity)-[mention:MENTIONED_IN {id: row.id}]->(chunk)
            SET mention.doc_id = row.doc_id,
                mention.chunk_id = row.chunk_id,
                mention.partition_key = row.partition_key,
                mention.group_path = row.group_path,
                mention.clearance_level = row.clearance_level,
                mention.clearance_rank = row.clearance_rank,
                mention.is_current = row.is_current,
                mention.evidence_text = row.evidence_text,
                mention.confidence = row.confidence,
                mention.updated_at = datetime()
            """,
            {"rows": rows},
        )

    def _upsert_relationships(self, extractions: list[GraphExtractionResult], *, partition: str) -> None:
        group_path, clearance_rank = _partition_parts(partition)
        clearance_level = _clearance_from_rank(clearance_rank)
        rows = [
            {
                "id": relationship.id,
                "source_entity_id": relationship.source_entity_id,
                "target_entity_id": relationship.target_entity_id,
                "type": relationship.type,
                "description": relationship.description,
                "doc_id": relationship.doc_id,
                "chunk_id": relationship.chunk_id,
                "evidence_text": relationship.evidence_text,
                "confidence": relationship.confidence,
                "weight": relationship.weight,
                "partition_key": partition,
                "group_path": group_path,
                "clearance_level": clearance_level,
                "clearance_rank": clearance_rank,
                "is_current": True,
            }
            for extraction in extractions
            for relationship in extraction.relationships
        ]
        self._run(
            """
            UNWIND $rows AS row
            MATCH (source:GraphEntity {id: row.source_entity_id})
            MATCH (target:GraphEntity {id: row.target_entity_id})
            MERGE (source)-[rel:RELATES_TO {id: row.id}]->(target)
            SET rel.type = row.type,
                rel.description = row.description,
                rel.doc_id = row.doc_id,
                rel.chunk_id = row.chunk_id,
                rel.evidence_text = row.evidence_text,
                rel.confidence = row.confidence,
                rel.weight = row.weight,
                rel.partition_key = row.partition_key,
                rel.group_path = row.group_path,
                rel.clearance_level = row.clearance_level,
                rel.clearance_rank = row.clearance_rank,
                rel.is_current = row.is_current,
                rel.updated_at = datetime()
            """,
            {"rows": rows},
        )

    def _upsert_claims(self, extractions: list[GraphExtractionResult], *, partition: str) -> None:
        group_path, clearance_rank = _partition_parts(partition)
        clearance_level = _clearance_from_rank(clearance_rank)
        rows = [
            {
                "id": claim.id,
                "entity_id": claim.entity_id,
                "entity_name": claim.entity_name,
                "claim": claim.claim,
                "doc_id": claim.doc_id,
                "chunk_id": claim.chunk_id,
                "evidence_text": claim.evidence_text,
                "confidence": claim.confidence,
                "partition_key": partition,
                "group_path": group_path,
                "clearance_level": clearance_level,
                "clearance_rank": clearance_rank,
                "is_current": True,
            }
            for extraction in extractions
            for claim in extraction.claims
        ]
        self._run(
            """
            UNWIND $rows AS row
            MATCH (entity:GraphEntity {id: row.entity_id})
            MATCH (chunk:Chunk {id: row.chunk_id})
            MERGE (claim:GraphClaim {id: row.id})
            SET claim.entity_name = row.entity_name,
                claim.claim = row.claim,
                claim.doc_id = row.doc_id,
                claim.chunk_id = row.chunk_id,
                claim.partition_key = row.partition_key,
                claim.group_path = row.group_path,
                claim.clearance_level = row.clearance_level,
                claim.clearance_rank = row.clearance_rank,
                claim.is_current = row.is_current,
                claim.evidence_text = row.evidence_text,
                claim.confidence = row.confidence,
                claim.updated_at = datetime()
            MERGE (entity)-[:HAS_CLAIM]->(claim)
            MERGE (claim)-[:SUPPORTED_BY]->(chunk)
            """,
            {"rows": rows},
        )

    def _run(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        params = params or {}
        try:
            with self.driver.session(database=self.config.database) as session:
                result = session.run(query, **params)
                data = result.data()
                consume = getattr(result, "consume", None)
                if callable(consume):
                    consume()
                return [dict(row) for row in data]
        except Exception as exc:
            raise Neo4jGraphStoreError(str(exc)) from exc


_SCHEMA_QUERIES = (
    "CREATE CONSTRAINT graph_document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT graph_chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT graph_entity_id IF NOT EXISTS FOR (n:GraphEntity) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT graph_claim_id IF NOT EXISTS FOR (n:GraphClaim) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT graph_community_id IF NOT EXISTS FOR (n:Community) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT graph_summary_id IF NOT EXISTS FOR (n:CommunitySummary) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX graph_entity_partition IF NOT EXISTS FOR (n:GraphEntity) ON (n.partition_key)",
    "CREATE INDEX graph_chunk_partition IF NOT EXISTS FOR (n:Chunk) ON (n.partition_key)",
    "CREATE INDEX graph_summary_partition IF NOT EXISTS FOR (n:CommunitySummary) ON (n.partition_key)",
)


def _document_params(document: GraphDocument) -> dict[str, Any]:
    return {
        "id": document.doc_id,
        "title": document.title,
        "group_path": document.group_path,
        "clearance_level": document.clearance_level,
        "clearance_rank": document.clearance_rank,
        "partition_key": document.partition_key,
        "is_current": document.is_current,
    }


def _chunk_params(chunk: ChunkRecord) -> dict[str, Any]:
    return {
        "doc_id": chunk.doc_id,
        "chunk_id": chunk.chunk_id,
        "text": chunk.text,
        "group_path": chunk.group_path,
        "clearance_level": chunk.clearance_level,
        "clearance_rank": chunk.clearance_rank,
        "partition_key": chunk.partition_key,
        "is_current": chunk.is_current,
        "page": chunk.page,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
    }


def _unique_by_id(items: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for item in items:
        item_id = str(getattr(item, "id"))
        if item_id in seen:
            continue
        seen.add(item_id)
        unique.append(item)
    return unique


def _dedupe_refs(refs: list[SourceRef]) -> list[SourceRef]:
    seen: set[tuple[str, str]] = set()
    unique: list[SourceRef] = []
    for ref in refs:
        key = (ref.doc_id, ref.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _gds_graph_name(partition: str) -> str:
    return "graphrag_" + "".join(ch if ch.isalnum() else "_" for ch in partition)[-80:]


def _partition_parts(partition: str) -> tuple[str, int]:
    if "|clearance:" not in partition:
        return partition, 1
    group_path, rank = partition.rsplit("|clearance:", 1)
    try:
        return group_path, int(rank)
    except ValueError:
        return group_path, 1


def _clearance_from_rank(rank: int) -> str:
    levels = ("NATO_UNCLASSIFIED", "NATO_RESTRICTED", "NATO_CONFIDENTIAL", "NATO_SECRET", "COSMIC_TOP_SECRET")
    return levels[max(0, min(len(levels) - 1, rank))]
