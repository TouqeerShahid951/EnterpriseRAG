"""Qdrant HTTP adapter for local RAG retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from rag.shared.contracts.qdrant_schema import (
    DENSE_VECTOR_NAME,
    LEGACY_DENSE_MODE,
    SPARSE_VECTOR_NAME,
    collection_mode,
    collection_vector_size,
)

from .cancellation import QueryCancellationToken
from .http import ServiceRequestError, request_json


@dataclass(frozen=True)
class SearchHit:
    point_id: str
    score: float
    payload: dict[str, Any]


class QdrantClient:
    def __init__(self, *, base_url: str, collection: str, timeout_seconds: float) -> None:
        self.base_url = base_url
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self._collection_path = f"/collections/{quote(collection, safe='')}"
        self._collection_mode: str | None = None

    def prepare_for_query(self, vector_size: int, *, cancellation_token: QueryCancellationToken | None = None) -> bool:
        try:
            payload = request_json(
                self.base_url,
                self._collection_path,
                service="qdrant",
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
            self._collection_mode = _validated_mode(payload, vector_size)
            return True
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                self._collection_mode = None
                return False
            raise

    def current_vector_size(self, *, cancellation_token: QueryCancellationToken | None = None) -> int | None:
        try:
            payload = request_json(
                self.base_url,
                self._collection_path,
                service="qdrant",
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                return None
            raise
        return collection_vector_size(payload)

    def search(
        self,
        vector: list[float],
        *,
        limit: int,
        qdrant_filter: dict[str, Any],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> list[SearchHit]:
        response = request_json(
            self.base_url,
            f"{self._collection_path}/points/search",
            service="qdrant",
            method="POST",
            payload=_dense_search_payload(vector=vector, limit=limit, qdrant_filter=qdrant_filter),
            timeout_seconds=self.timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _parse_search_hits(response)

    def hybrid_search(
        self,
        *,
        dense_vector: list[float],
        sparse_vector: dict[str, Any],
        limit: int,
        qdrant_filter: dict[str, Any],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> list[SearchHit]:
        if self._collection_mode == LEGACY_DENSE_MODE:
            return self.search(
                dense_vector,
                limit=limit,
                qdrant_filter=qdrant_filter,
                cancellation_token=cancellation_token,
            )
        response = request_json(
            self.base_url,
            f"{self._collection_path}/points/query",
            service="qdrant",
            method="POST",
            payload=_hybrid_query_payload(
                dense_vector=dense_vector,
                sparse_vector=sparse_vector,
                limit=limit,
                qdrant_filter=qdrant_filter,
            ),
            timeout_seconds=self.timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _parse_query_hits(response)

    def retrieve_chunks(
        self,
        chunk_refs: list[tuple[str, str]],
        *,
        qdrant_filter: dict[str, Any],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> list[SearchHit]:
        if not chunk_refs:
            return []
        scoped_filter = dict(qdrant_filter)
        must = list(scoped_filter.get("must", []))
        must.append(
            {
                "should": [
                    {
                        "must": [
                            {"key": "doc_id", "match": {"value": doc_id}},
                            {"key": "chunk_id", "match": {"value": chunk_id}},
                        ]
                    }
                    for doc_id, chunk_id in chunk_refs
                ]
            }
        )
        scoped_filter["must"] = must
        response = request_json(
            self.base_url,
            f"{self._collection_path}/points/scroll",
            service="qdrant",
            method="POST",
            payload={
                "filter": scoped_filter,
                "limit": len(chunk_refs),
                "with_payload": True,
                "with_vector": False,
            },
            timeout_seconds=self.timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _parse_scroll_hits(response)

    def retrieve_source_chunk(
        self,
        *,
        doc_id: str,
        chunk_id: str,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> SearchHit | None:
        response = request_json(
            self.base_url,
            f"{self._collection_path}/points/scroll",
            service="qdrant",
            method="POST",
            payload={
                "filter": {
                    "must": [
                        {"key": "doc_id", "match": {"value": doc_id}},
                        {"key": "chunk_id", "match": {"value": chunk_id}},
                    ]
                },
                "limit": 1,
                "with_payload": True,
                "with_vector": False,
            },
            timeout_seconds=self.timeout_seconds,
            cancellation_token=cancellation_token,
        )
        hits = _parse_scroll_hits(response)
        return hits[0] if hits else None

    def retrieve_table_rows(
        self,
        *,
        doc_id: str,
        table_title: str,
        qdrant_filter: dict[str, Any],
        limit: int,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> list[SearchHit]:
        if not doc_id or not table_title or limit <= 0:
            return []
        scoped_filter = dict(qdrant_filter)
        must = list(scoped_filter.get("must", []))
        must.extend(
            [
                {"key": "doc_id", "match": {"value": doc_id}},
                {"key": "table_title", "match": {"value": table_title}},
                {"key": "chunk_type", "match": {"value": "table_row"}},
            ]
        )
        scoped_filter["must"] = must
        response = request_json(
            self.base_url,
            f"{self._collection_path}/points/scroll",
            service="qdrant",
            method="POST",
            payload={
                "filter": scoped_filter,
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
            timeout_seconds=self.timeout_seconds,
            cancellation_token=cancellation_token,
        )
        return _parse_scroll_hits(response)

    def retrieve_document_chunks(
        self,
        *,
        document_ids: list[str],
        qdrant_filter: dict[str, Any],
        structured_only: bool,
        limit: int,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> list[SearchHit]:
        scoped_ids = sorted({doc_id.strip() for doc_id in document_ids if doc_id.strip()})
        if not scoped_ids or limit <= 0:
            return []
        scoped_filter = dict(qdrant_filter)
        must = list(scoped_filter.get("must", []))
        if structured_only:
            must.append({
                "should": [
                    {"key": "chunk_type", "match": {"value": "table_row"}},
                    {"key": "structured_kind", "match": {"value": "table_row"}},
                    {"key": "structured_kind", "match": {"value": "kv_record"}},
                ]
            })
        scoped_filter["must"] = must
        hits: list[SearchHit] = []
        offset: Any | None = None
        while len(hits) < limit:
            page_size = min(256, limit - len(hits))
            payload: dict[str, Any] = {
                "filter": scoped_filter,
                "limit": page_size,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            response = request_json(
                self.base_url,
                f"{self._collection_path}/points/scroll",
                service="qdrant",
                method="POST",
                payload=payload,
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
            page = _parse_scroll_hits(response)
            hits.extend(page)
            result = response.get("result")
            next_offset = result.get("next_page_offset") if isinstance(result, dict) else None
            if not page or next_offset is None:
                break
            offset = next_offset
        annotated: list[SearchHit] = []
        for hit in hits:
            payload = dict(hit.payload)
            payload["artifact_scan_origin"] = "authorized_document_scope"
            annotated.append(SearchHit(point_id=hit.point_id, score=hit.score, payload=payload))
        return annotated

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, Any],
        structured_only: bool,
        limit: int,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> list[SearchHit]:
        if limit <= 0:
            return []
        scoped_filter = dict(qdrant_filter)
        must = list(scoped_filter.get("must", []))
        if structured_only:
            must.append({
                "should": [
                    {"key": "chunk_type", "match": {"value": "table_row"}},
                    {"key": "structured_kind", "match": {"value": "table_row"}},
                    {"key": "structured_kind", "match": {"value": "kv_record"}},
                ]
            })
        scoped_filter["must"] = must
        hits: list[SearchHit] = []
        offset: Any | None = None
        while len(hits) < limit:
            page_size = min(256, limit - len(hits))
            payload: dict[str, Any] = {
                "filter": scoped_filter,
                "limit": page_size,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            response = request_json(
                self.base_url,
                f"{self._collection_path}/points/scroll",
                service="qdrant",
                method="POST",
                payload=payload,
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
            page = _parse_scroll_hits(response)
            hits.extend(page)
            result = response.get("result")
            next_offset = result.get("next_page_offset") if isinstance(result, dict) else None
            if not page or next_offset is None:
                break
            offset = next_offset
        annotated: list[SearchHit] = []
        for hit in hits:
            payload = dict(hit.payload)
            payload["artifact_scan_origin"] = "authorized_scope"
            annotated.append(SearchHit(point_id=hit.point_id, score=hit.score, payload=payload))
        return annotated

    def delete_document_points(self, doc_id: str, *, cancellation_token: QueryCancellationToken | None = None) -> None:
        try:
            request_json(
                self.base_url,
                f"{self._collection_path}/points/delete?wait=true",
                service="qdrant",
                method="POST",
                payload={"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}},
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                return
            raise

    def set_document_clearance(
        self,
        doc_id: str,
        *,
        clearance_level: str,
        clearance_rank: int,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> None:
        try:
            request_json(
                self.base_url,
                f"{self._collection_path}/points/payload?wait=true",
                service="qdrant",
                method="POST",
                payload={
                    "payload": {
                        "clearance_level": clearance_level,
                        "clearance_rank": clearance_rank,
                    },
                    "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
                },
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                return
            raise

    def set_document_topics(
        self,
        doc_id: str,
        *,
        topics: list[str],
        llm_topics: list[str],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> None:
        try:
            request_json(
                self.base_url,
                f"{self._collection_path}/points/payload?wait=true",
                service="qdrant",
                method="POST",
                payload={
                    "payload": {
                        "topics": topics,
                        "llm_topics": llm_topics,
                    },
                    "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
                },
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                return
            raise

    def set_document_acl_group_paths(
        self,
        doc_id: str,
        *,
        acl_group_paths: list[str],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> None:
        try:
            request_json(
                self.base_url,
                f"{self._collection_path}/points/payload?wait=true",
                service="qdrant",
                method="POST",
                payload={
                    "payload": {
                        "acl_group_paths": acl_group_paths,
                    },
                    "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
                },
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                return
            raise

    def set_document_access_scope(
        self,
        doc_id: str,
        *,
        group_path: str,
        acl_group_paths: list[str],
        cancellation_token: QueryCancellationToken | None = None,
    ) -> None:
        try:
            request_json(
                self.base_url,
                f"{self._collection_path}/points/payload?wait=true",
                service="qdrant",
                method="POST",
                payload={
                    "payload": {
                        "group_path": group_path,
                        "acl_group_paths": acl_group_paths,
                    },
                    "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
                },
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                return
            raise

    def set_document_retrieval_status(
        self,
        doc_id: str,
        *,
        retrieval_status: str,
        source_deleted: bool,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> None:
        try:
            request_json(
                self.base_url,
                f"{self._collection_path}/points/payload?wait=true",
                service="qdrant",
                method="POST",
                payload={
                    "payload": {
                        "retrieval_status": retrieval_status,
                        "source_deleted": source_deleted,
                    },
                    "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
                },
                timeout_seconds=self.timeout_seconds,
                cancellation_token=cancellation_token,
            )
        except ServiceRequestError as exc:
            if exc.status_code == 404:
                return
            raise


def _validated_mode(payload: dict[str, Any], vector_size: int) -> str:
    mode = collection_mode(payload, vector_size)
    if mode:
        return mode
    existing_size = collection_vector_size(payload)
    raise ServiceRequestError(
        "qdrant",
        f"collection vector schema does not match embedding size {vector_size}; found {existing_size}",
        409,
    )


def _hybrid_query_payload(
    *,
    dense_vector: list[float],
    sparse_vector: dict[str, Any],
    limit: int,
    qdrant_filter: dict[str, Any],
) -> dict[str, Any]:
    prefetch = [
        {
            "query": dense_vector,
            "using": DENSE_VECTOR_NAME,
            "limit": limit,
            "filter": qdrant_filter,
        }
    ]
    if sparse_vector.get("indices"):
        prefetch.insert(
            0,
            {
                "query": sparse_vector,
                "using": SPARSE_VECTOR_NAME,
                "limit": limit,
                "filter": qdrant_filter,
            },
        )
    return {
        "prefetch": prefetch,
        "query": {"fusion": "rrf"},
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
    }


def _dense_search_payload(
    *,
    vector: list[float],
    limit: int,
    qdrant_filter: dict[str, Any],
) -> dict[str, Any]:
    return {
        "vector": vector,
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
        "filter": qdrant_filter,
    }


def _parse_search_hits(response: dict[str, Any]) -> list[SearchHit]:
    result = response.get("result")
    if not isinstance(result, list):
        raise ServiceRequestError("qdrant", "search response did not include result hits")
    return _parse_hit_items(result)


def _parse_query_hits(response: dict[str, Any]) -> list[SearchHit]:
    result = response.get("result")
    points = result.get("points") if isinstance(result, dict) else None
    if not isinstance(points, list):
        raise ServiceRequestError("qdrant", "query response did not include result points")
    return _parse_hit_items(points)


def _parse_scroll_hits(response: dict[str, Any]) -> list[SearchHit]:
    result = response.get("result")
    points = result.get("points") if isinstance(result, dict) else None
    if not isinstance(points, list):
        raise ServiceRequestError("qdrant", "scroll response did not include result points")
    return _parse_hit_items(points)


def _parse_hit_items(items: list[Any]) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        payload_value = item.get("payload")
        hits.append(
            SearchHit(
                point_id=str(item.get("id", "")),
                score=float(item.get("score", 0.0)),
                payload=payload_value if isinstance(payload_value, dict) else {},
            )
        )
    return hits
