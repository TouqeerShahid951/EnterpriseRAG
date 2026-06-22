"""Qdrant helpers for GraphRAG source chunks and community summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5
import json
import urllib.error
import urllib.request

from rag.shared.contracts.qdrant_schema import DENSE_VECTOR_NAME

from .models import ChunkRecord, CommunitySummary, SourceRef


class QdrantGraphRAGError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommunitySearchHit:
    id: str
    score: float
    summary: CommunitySummary


class QdrantGraphRAGClient:
    def __init__(
        self,
        *,
        base_url: str,
        documents_collection: str,
        community_collection: str,
        timeout_seconds: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.documents_collection = documents_collection
        self.community_collection = community_collection
        self.timeout_seconds = timeout_seconds

    def retrieve_document_chunks(self, doc_id: str, *, limit: int = 5000) -> list[ChunkRecord]:
        response = self._request(
            "POST",
            f"/collections/{quote(self.documents_collection, safe='')}/points/scroll",
            {
                "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        return [_chunk_from_payload(point.get("payload")) for point in _points(response) if isinstance(point.get("payload"), dict)]

    def retrieve_chunks_by_refs(
        self,
        refs: list[SourceRef],
        *,
        qdrant_filter: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not refs:
            return []
        scoped = dict(qdrant_filter or {})
        must = list(scoped.get("must", []))
        must.append(
            {
                "should": [
                    {
                        "must": [
                            {"key": "doc_id", "match": {"value": ref.doc_id}},
                            {"key": "chunk_id", "match": {"value": ref.chunk_id}},
                        ]
                    }
                    for ref in refs
                ]
            }
        )
        scoped["must"] = must
        response = self._request(
            "POST",
            f"/collections/{quote(self.documents_collection, safe='')}/points/scroll",
            {
                "filter": scoped,
                "limit": limit or len(refs),
                "with_payload": True,
                "with_vector": False,
            },
        )
        return [dict(point.get("payload")) for point in _points(response) if isinstance(point.get("payload"), dict)]

    def ensure_community_collection(self, vector_size: int) -> None:
        path = f"/collections/{quote(self.community_collection, safe='')}"
        try:
            self._request("GET", path, None)
            self._ensure_payload_indexes()
            return
        except QdrantGraphRAGError as exc:
            if "HTTP 404" not in str(exc):
                raise
        self._request(
            "PUT",
            path,
            {
                "vectors": {
                    DENSE_VECTOR_NAME: {
                        "size": vector_size,
                        "distance": "Cosine",
                    }
                }
            },
        )
        self._ensure_payload_indexes()

    def replace_partition_summaries(
        self,
        *,
        partition_key: str,
        summaries: list[CommunitySummary],
        vectors: list[list[float]],
    ) -> None:
        if len(summaries) != len(vectors):
            raise ValueError("summaries and vectors must have the same length")
        if vectors:
            self.ensure_community_collection(len(vectors[0]))
        self._delete_partition(partition_key)
        points = [
            {
                "id": str(uuid5(NAMESPACE_URL, f"graphrag-community-summary:{summary.id}")),
                "vector": {DENSE_VECTOR_NAME: vector},
                "payload": _summary_payload(summary),
            }
            for summary, vector in zip(summaries, vectors, strict=True)
        ]
        if points:
            self._request(
                "PUT",
                f"/collections/{quote(self.community_collection, safe='')}/points?wait=true",
                {"points": points},
            )

    def search_summaries(
        self,
        *,
        vector: list[float],
        qdrant_filter: dict[str, Any],
        limit: int,
    ) -> list[CommunitySearchHit]:
        response = self._request(
            "POST",
            f"/collections/{quote(self.community_collection, safe='')}/points/search",
            {
                "vector": {"name": DENSE_VECTOR_NAME, "vector": vector},
                "filter": qdrant_filter,
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        result = response.get("result")
        if not isinstance(result, list):
            raise QdrantGraphRAGError("Qdrant summary search response did not include hits")
        hits: list[CommunitySearchHit] = []
        for item in result:
            if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                continue
            hits.append(
                CommunitySearchHit(
                    id=str(item.get("id", "")),
                    score=float(item.get("score", 0.0)),
                    summary=_summary_from_payload(item["payload"]),
                )
            )
        return hits

    def _delete_partition(self, partition_key: str) -> None:
        try:
            self._request(
                "POST",
                f"/collections/{quote(self.community_collection, safe='')}/points/delete?wait=true",
                {"filter": {"must": [{"key": "partition_key", "match": {"value": partition_key}}]}},
            )
        except QdrantGraphRAGError as exc:
            if "HTTP 404" not in str(exc):
                raise

    def _ensure_payload_indexes(self) -> None:
        for field_name, field_schema in _COMMUNITY_PAYLOAD_INDEXES:
            try:
                self._request(
                    "PUT",
                    f"/collections/{quote(self.community_collection, safe='')}/index",
                    {"field_name": field_name, "field_schema": field_schema},
                )
            except QdrantGraphRAGError as exc:
                if "HTTP 409" not in str(exc):
                    raise

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise QdrantGraphRAGError(f"Qdrant HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise QdrantGraphRAGError(f"Qdrant request failed: {exc}") from exc


_COMMUNITY_PAYLOAD_INDEXES: tuple[tuple[str, str], ...] = (
    ("community_id", "keyword"),
    ("partition_key", "keyword"),
    ("group_path", "keyword"),
    ("clearance_level", "keyword"),
    ("clearance_rank", "integer"),
    ("source_doc_ids", "keyword"),
    ("source_chunk_ids", "keyword"),
    ("graph_level", "integer"),
    ("is_current", "bool"),
)


def _points(response: dict[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result")
    points = result.get("points") if isinstance(result, dict) else None
    if not isinstance(points, list):
        raise QdrantGraphRAGError("Qdrant scroll response did not include points")
    return [point for point in points if isinstance(point, dict)]


def _chunk_from_payload(payload: object) -> ChunkRecord:
    if not isinstance(payload, dict):
        raise QdrantGraphRAGError("Qdrant point had no payload")
    return ChunkRecord(
        doc_id=str(payload.get("doc_id", "")),
        chunk_id=str(payload.get("chunk_id", "")),
        text=str(payload.get("text", "") or ""),
        doc_title=str(payload.get("doc_title") or payload.get("source_id") or payload.get("doc_id") or "Untitled"),
        group_path=str(payload.get("group_path") or "/"),
        clearance_level=str(payload.get("clearance_level") or "NATO_RESTRICTED"),
        clearance_rank=int(payload.get("clearance_rank") or 1),
        is_current=bool(payload.get("is_current", True)),
        page=_optional_int(payload.get("page")),
        page_start=_optional_int(payload.get("page_start")),
        page_end=_optional_int(payload.get("page_end")),
    )


def _summary_payload(summary: CommunitySummary) -> dict[str, Any]:
    source_doc_ids = sorted({ref.doc_id for ref in summary.source_refs})
    source_chunk_ids = sorted({ref.chunk_id for ref in summary.source_refs})
    return {
        "community_id": summary.community_id,
        "summary_id": summary.id,
        "partition_key": summary.partition_key,
        "group_path": summary.group_path,
        "clearance_level": summary.clearance_level,
        "clearance_rank": summary.clearance_rank,
        "graph_level": summary.level,
        "title": summary.title,
        "text": summary.summary,
        "summary": summary.summary,
        "important_entities": summary.important_entities,
        "important_relationships": summary.important_relationships,
        "entity_ids": summary.entity_ids,
        "source_doc_ids": source_doc_ids,
        "source_chunk_ids": source_chunk_ids,
        "source_refs": [{"doc_id": ref.doc_id, "chunk_id": ref.chunk_id} for ref in summary.source_refs],
        "is_current": True,
    }


def _summary_from_payload(payload: dict[str, Any]) -> CommunitySummary:
    refs = [
        SourceRef(doc_id=str(item.get("doc_id", "")), chunk_id=str(item.get("chunk_id", "")))
        for item in payload.get("source_refs", [])
        if isinstance(item, dict) and item.get("doc_id") and item.get("chunk_id")
    ]
    return CommunitySummary(
        id=str(payload.get("summary_id") or payload.get("community_id") or ""),
        community_id=str(payload.get("community_id") or ""),
        partition_key=str(payload.get("partition_key") or ""),
        group_path=str(payload.get("group_path") or "/"),
        clearance_level=str(payload.get("clearance_level") or "NATO_RESTRICTED"),
        clearance_rank=int(payload.get("clearance_rank") or 1),
        level=int(payload.get("graph_level") or 0),
        title=str(payload.get("title") or "Community"),
        summary=str(payload.get("summary") or payload.get("text") or ""),
        important_entities=[str(item) for item in payload.get("important_entities", []) if str(item).strip()]
        if isinstance(payload.get("important_entities"), list)
        else [],
        important_relationships=[str(item) for item in payload.get("important_relationships", []) if str(item).strip()]
        if isinstance(payload.get("important_relationships"), list)
        else [],
        source_refs=refs,
        entity_ids=[str(item) for item in payload.get("entity_ids", []) if str(item).strip()]
        if isinstance(payload.get("entity_ids"), list)
        else [],
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None
