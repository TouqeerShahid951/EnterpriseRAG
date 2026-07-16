"""Qdrant HTTP adapter for local RAG retrieval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
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
    def __init__(
        self,
        *,
        base_url: str,
        collection: str,
        timeout_seconds: float,
        active_generation_resolver: Callable[
            [list[str], bool], dict[str, str | None]
        ] | None = None,
    ) -> None:
        self.base_url = base_url
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self._collection_path = f"/collections/{quote(collection, safe='')}"
        self._collection_mode: str | None = None
        self._active_generation_resolver = active_generation_resolver

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
        current_only = _is_current_only_filter(qdrant_filter)
        return self._refill_ranked_generation_hits(
            limit=limit,
            current_only=current_only,
            fetch_page=lambda offset, page_size: _parse_search_hits(
                request_json(
                    self.base_url,
                    f"{self._collection_path}/points/search",
                    service="qdrant",
                    method="POST",
                    payload=_dense_search_payload(
                        vector=vector,
                        limit=page_size,
                        offset=offset,
                        qdrant_filter=qdrant_filter,
                    ),
                    timeout_seconds=self.timeout_seconds,
                    cancellation_token=cancellation_token,
                )
            ),
        )

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
        current_only = _is_current_only_filter(qdrant_filter)
        return self._refill_ranked_generation_hits(
            limit=limit,
            current_only=current_only,
            fetch_page=lambda offset, page_size: _parse_query_hits(
                request_json(
                    self.base_url,
                    f"{self._collection_path}/points/query",
                    service="qdrant",
                    method="POST",
                    payload=_hybrid_query_payload(
                        dense_vector=dense_vector,
                        sparse_vector=sparse_vector,
                        limit=page_size,
                        offset=offset,
                        qdrant_filter=qdrant_filter,
                    ),
                    timeout_seconds=self.timeout_seconds,
                    cancellation_token=cancellation_token,
                )
            ),
        )

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
        return self._refill_scroll_generation_hits(
            qdrant_filter=scoped_filter,
            limit=len(chunk_refs),
            current_only=_is_current_only_filter(scoped_filter),
            cancellation_token=cancellation_token,
        )

    def retrieve_source_chunk(
        self,
        *,
        doc_id: str,
        chunk_id: str,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> SearchHit | None:
        hits = self._refill_scroll_generation_hits(
            qdrant_filter={
                "must": [
                    {"key": "doc_id", "match": {"value": doc_id}},
                    {"key": "chunk_id", "match": {"value": chunk_id}},
                ]
            },
            limit=1,
            current_only=False,
            cancellation_token=cancellation_token,
        )
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
        return self._refill_scroll_generation_hits(
            qdrant_filter=scoped_filter,
            limit=limit,
            current_only=_is_current_only_filter(scoped_filter),
            cancellation_token=cancellation_token,
        )

    def retrieve_document_chunks(
        self,
        *,
        document_ids: list[str],
        qdrant_filter: dict[str, Any],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> list[SearchHit]:
        scoped_ids = sorted({doc_id.strip() for doc_id in document_ids if doc_id.strip()})
        if not scoped_ids or limit <= 0:
            return []
        scoped_filter = dict(qdrant_filter)
        must = list(scoped_filter.get("must", []))
        must.append(
            {
                "should": [
                    {"key": "doc_id", "match": {"value": document_id}}
                    for document_id in scoped_ids
                ]
            }
        )
        if structured_only:
            must.append({
                "should": [
                    {"key": "chunk_type", "match": {"value": "table_row"}},
                    {"key": "structured_kind", "match": {"value": "table_row"}},
                    {"key": "structured_kind", "match": {"value": "kv_record"}},
                ]
            })
        scoped_filter["must"] = must
        scan_limit = limit + 1
        hits: list[SearchHit] = []
        active_generations = self._resolved_generations(
            scoped_ids,
            current_only=_is_current_only_filter(scoped_filter),
        )
        offset: Any | None = None
        next_offset: Any | None = None
        deadline_exceeded = False
        while len(hits) < scan_limit:
            if deadline is not None and monotonic() >= deadline:
                deadline_exceeded = True
                break
            page_size = min(256, scan_limit - len(hits))
            payload: dict[str, Any] = {
                "filter": scoped_filter,
                "limit": page_size,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            try:
                response = request_json(
                    self.base_url,
                    f"{self._collection_path}/points/scroll",
                    service="qdrant",
                    method="POST",
                    payload=payload,
                    timeout_seconds=_bounded_timeout(
                        self.timeout_seconds,
                        deadline,
                    ),
                    cancellation_token=cancellation_token,
                )
            except ServiceRequestError:
                if deadline is not None and monotonic() >= deadline:
                    deadline_exceeded = True
                    break
                raise
            page = self._filter_active_generation_hits(
                _parse_scroll_hits(response), active_generations
            )
            hits.extend(page)
            result = response.get("result")
            next_offset = result.get("next_page_offset") if isinstance(result, dict) else None
            if next_offset is None:
                break
            offset = next_offset
        scan_complete = (
            not deadline_exceeded
            and len(hits) <= limit
            and next_offset is None
        )
        annotated: list[SearchHit] = []
        for hit in hits[:limit]:
            payload = dict(hit.payload)
            payload["artifact_scan_origin"] = "authorized_document_scope"
            payload["authorized_scan_complete"] = scan_complete
            annotated.append(SearchHit(point_id=hit.point_id, score=hit.score, payload=payload))
        return annotated

    def retrieve_authorized_chunks(
        self,
        *,
        qdrant_filter: dict[str, Any],
        structured_only: bool,
        limit: int,
        deadline: float | None = None,
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
        scan_limit = limit + 1
        hits: list[SearchHit] = []
        active_generations: dict[str, str | None] = {}
        current_only = _is_current_only_filter(scoped_filter)
        offset: Any | None = None
        next_offset: Any | None = None
        deadline_exceeded = False
        while len(hits) < scan_limit:
            if deadline is not None and monotonic() >= deadline:
                deadline_exceeded = True
                break
            page_size = min(256, scan_limit - len(hits))
            payload: dict[str, Any] = {
                "filter": scoped_filter,
                "limit": page_size,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            try:
                response = request_json(
                    self.base_url,
                    f"{self._collection_path}/points/scroll",
                    service="qdrant",
                    method="POST",
                    payload=payload,
                    timeout_seconds=_bounded_timeout(
                        self.timeout_seconds,
                        deadline,
                    ),
                    cancellation_token=cancellation_token,
                )
            except ServiceRequestError:
                if deadline is not None and monotonic() >= deadline:
                    deadline_exceeded = True
                    break
                raise
            raw_page = _parse_scroll_hits(response)
            active_generations.update(
                self._resolved_generations(
                    [
                        str(hit.payload.get("doc_id") or "").strip()
                        for hit in raw_page
                        if str(hit.payload.get("doc_id") or "").strip()
                        not in active_generations
                    ],
                    current_only=current_only,
                )
            )
            page = self._filter_active_generation_hits(raw_page, active_generations)
            hits.extend(page)
            result = response.get("result")
            next_offset = result.get("next_page_offset") if isinstance(result, dict) else None
            if next_offset is None:
                break
            offset = next_offset
        scan_complete = (
            not deadline_exceeded
            and len(hits) <= limit
            and next_offset is None
        )
        annotated: list[SearchHit] = []
        for hit in hits[:limit]:
            payload = dict(hit.payload)
            payload["artifact_scan_origin"] = "authorized_scope"
            payload["authorized_scan_complete"] = scan_complete
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

    def _refill_ranked_generation_hits(
        self,
        *,
        limit: int,
        current_only: bool,
        fetch_page: Callable[[int, int], list[SearchHit]],
    ) -> list[SearchHit]:
        if limit <= 0:
            return []
        if self._active_generation_resolver is None:
            return fetch_page(0, limit)[:limit]

        hits: list[SearchHit] = []
        active_generations: dict[str, str | None] = {}
        resolved_document_ids: set[str] = set()
        seen_point_ids: set[str] = set()
        page_size = _generation_page_size(limit)
        offset = 0
        while len(hits) < limit:
            page = fetch_page(offset, page_size)
            if not page:
                break
            _resolve_page_generations(
                self,
                page,
                active_generations=active_generations,
                resolved_document_ids=resolved_document_ids,
                current_only=current_only,
            )
            fresh_page = [
                hit for hit in page if hit.point_id not in seen_point_ids
            ]
            seen_point_ids.update(hit.point_id for hit in fresh_page)
            hits.extend(self._filter_active_generation_hits(fresh_page, active_generations))
            if len(page) < page_size:
                break
            offset += len(page)
        return hits[:limit]

    def _refill_scroll_generation_hits(
        self,
        *,
        qdrant_filter: dict[str, Any],
        limit: int,
        current_only: bool,
        cancellation_token: QueryCancellationToken | None,
    ) -> list[SearchHit]:
        if limit <= 0:
            return []

        hits: list[SearchHit] = []
        active_generations: dict[str, str | None] = {}
        resolved_document_ids: set[str] = set()
        seen_point_ids: set[str] = set()
        page_size = (
            _generation_page_size(limit)
            if self._active_generation_resolver is not None
            else limit
        )
        offset: Any | None = None
        while len(hits) < limit:
            payload: dict[str, Any] = {
                "filter": qdrant_filter,
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
            _resolve_page_generations(
                self,
                page,
                active_generations=active_generations,
                resolved_document_ids=resolved_document_ids,
                current_only=current_only,
            )
            fresh_page = [
                hit for hit in page if hit.point_id not in seen_point_ids
            ]
            seen_point_ids.update(hit.point_id for hit in fresh_page)
            hits.extend(self._filter_active_generation_hits(fresh_page, active_generations))
            result = response.get("result")
            offset = result.get("next_page_offset") if isinstance(result, dict) else None
            if offset is None:
                break
        return hits[:limit]

    def _resolved_generations(
        self,
        document_ids: list[str],
        *,
        current_only: bool,
    ) -> dict[str, str | None]:
        resolver = self._active_generation_resolver
        if resolver is None or not document_ids:
            return {}
        return resolver(sorted(set(document_ids)), current_only)

    def _filter_active_generation_hits(
        self,
        hits: list[SearchHit],
        active_generations: dict[str, str | None],
    ) -> list[SearchHit]:
        if self._active_generation_resolver is None:
            return hits
        return [
            hit for hit in hits if _matches_active_generation(hit, active_generations)
        ]


def _bounded_timeout(timeout_seconds: float, deadline: float | None) -> float:
    if deadline is None:
        return timeout_seconds
    return max(0.05, min(timeout_seconds, deadline - monotonic()))


def _resolve_page_generations(
    client: QdrantClient,
    hits: list[SearchHit],
    *,
    active_generations: dict[str, str | None],
    resolved_document_ids: set[str],
    current_only: bool,
) -> None:
    document_ids = [
        document_id
        for hit in hits
        if (document_id := str(hit.payload.get("doc_id") or "").strip())
        and document_id not in resolved_document_ids
    ]
    if not document_ids:
        return
    resolved_document_ids.update(document_ids)
    active_generations.update(
        client._resolved_generations(document_ids, current_only=current_only)
    )


def _generation_page_size(limit: int) -> int:
    return min(max(1, limit * 4), 256)


def _is_current_only_filter(qdrant_filter: dict[str, Any]) -> bool:
    for condition in qdrant_filter.get("must", []):
        if not isinstance(condition, dict) or condition.get("key") != "is_current":
            continue
        match = condition.get("match")
        if isinstance(match, dict) and match.get("value") is True:
            return True
    return False


def _matches_active_generation(
    hit: SearchHit,
    active_generations: dict[str, str | None],
) -> bool:
    document_id = str(hit.payload.get("doc_id") or "").strip()
    if not document_id or document_id not in active_generations:
        return False
    expected_generation = active_generations[document_id]
    generation_id = hit.payload.get("index_generation_id")
    if generation_id is None or not str(generation_id).strip():
        return expected_generation is None
    return (
        expected_generation == str(generation_id)
        and hit.payload.get("generation_published") is True
    )


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
    offset: int = 0,
    qdrant_filter: dict[str, Any],
) -> dict[str, Any]:
    prefetch_limit = limit + offset
    prefetch = [
        {
            "query": dense_vector,
            "using": DENSE_VECTOR_NAME,
            "limit": prefetch_limit,
            "filter": qdrant_filter,
        }
    ]
    if sparse_vector.get("indices"):
        prefetch.insert(
            0,
            {
                "query": sparse_vector,
                "using": SPARSE_VECTOR_NAME,
                "limit": prefetch_limit,
                "filter": qdrant_filter,
            },
        )
    payload: dict[str, Any] = {
        "prefetch": prefetch,
        "query": {"fusion": "rrf"},
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
    }
    if offset:
        payload["offset"] = offset
    return payload


def _dense_search_payload(
    *,
    vector: list[float],
    limit: int,
    offset: int = 0,
    qdrant_filter: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "vector": vector,
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
        "filter": qdrant_filter,
    }
    if offset:
        payload["offset"] = offset
    return payload


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
