"""Qdrant adapter for native PDF ingestion."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from rag.shared.contracts.qdrant_indexes import PAYLOAD_INDEXES
from rag.shared.contracts.qdrant_schema import (
    DENSE_VECTOR_NAME,
    HYBRID_MODE,
    LEGACY_DENSE_MODE,
    collection_mode,
    collection_vector_size,
    create_collection_payload,
)

from ..adapters.http import ServiceRequestError, request_json


class QdrantClient:
    def __init__(
        self,
        *,
        base_url: str,
        collection: str,
        timeout_seconds: float,
        upsert_batch_size: int = 64,
    ) -> None:
        self.base_url = base_url
        self.collection = collection
        self.timeout_seconds = timeout_seconds
        self.upsert_batch_size = max(1, upsert_batch_size)
        self._collection_path = f"/collections/{quote(collection, safe='')}"
        self._collection_mode: str | None = None

    def ensure_collection(self, vector_size: int) -> None:
        try:
            payload = request_json(
                self.base_url,
                self._collection_path,
                service="qdrant",
                timeout_seconds=self.timeout_seconds,
            )
            self._collection_mode = _validated_mode(payload, vector_size)
            self._ensure_payload_indexes()
            return
        except ServiceRequestError as exc:
            if exc.status_code != 404:
                raise

        request_json(
            self.base_url,
            self._collection_path,
            service="qdrant",
            method="PUT",
            payload=create_collection_payload(vector_size),
            timeout_seconds=self.timeout_seconds,
        )
        self._collection_mode = HYBRID_MODE
        self._ensure_payload_indexes()

    def replace_document(self, *, doc_id: str, points: list[dict[str, Any]]) -> int:
        self._delete_document_points(doc_id)
        current_point_ids = [
            str(point["id"])
            for point in points
            if not isinstance(point.get("payload"), dict) or point["payload"].get("is_current", True)
        ]
        staged_points = [
            point_for_collection_mode(_with_current_status(point, False), self._collection_mode)
            for point in points
        ]
        self._upsert_points(staged_points)
        self._set_points_current(current_point_ids)
        return len(points)

    def delete_document_points(self, doc_id: str) -> None:
        self._delete_document_points(doc_id)

    def mark_documents_not_current(self, doc_ids: list[str]) -> None:
        for doc_id in doc_ids:
            for point in self._document_points(doc_id):
                point_id = point.get("id")
                payload = point.get("payload")
                if not point_id or not isinstance(payload, dict):
                    raise ServiceRequestError("qdrant", "scroll response contained an invalid point", 502)
                self._set_point_payload(point_id=point_id, payload={**payload, "is_current": False})

    def _delete_document_points(self, doc_id: str) -> None:
        request_json(
            self.base_url,
            f"{self._collection_path}/points/delete?wait=true",
            service="qdrant",
            method="POST",
            payload={"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}},
            timeout_seconds=self.timeout_seconds,
        )

    def _upsert_points(self, points: list[dict[str, Any]]) -> None:
        for offset in range(0, len(points), self.upsert_batch_size):
            request_json(
                self.base_url,
                f"{self._collection_path}/points?wait=true",
                service="qdrant",
                method="PUT",
                payload={"points": points[offset : offset + self.upsert_batch_size]},
                timeout_seconds=self.timeout_seconds,
            )

    def _set_points_current(self, point_ids: list[str]) -> None:
        for offset in range(0, len(point_ids), self.upsert_batch_size):
            request_json(
                self.base_url,
                f"{self._collection_path}/points/payload?wait=true",
                service="qdrant",
                method="POST",
                payload={
                    "payload": {"is_current": True},
                    "points": point_ids[offset : offset + self.upsert_batch_size],
                },
                timeout_seconds=self.timeout_seconds,
            )

    def _document_points(self, doc_id: str) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        next_page_offset: Any = None
        while True:
            payload = scroll_payload(doc_id, next_page_offset)
            response = request_json(
                self.base_url,
                f"{self._collection_path}/points/scroll",
                service="qdrant",
                method="POST",
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
            result = response.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("points"), list):
                raise ServiceRequestError("qdrant", "scroll response did not include points", 502)
            points.extend(result["points"])
            next_page_offset = result.get("next_page_offset")
            if next_page_offset is None:
                return points

    def _set_point_payload(self, *, point_id: str, payload: dict[str, Any]) -> None:
        request_json(
            self.base_url,
            f"{self._collection_path}/points/payload?wait=true",
            service="qdrant",
            method="PUT",
            payload={"payload": payload, "points": [point_id]},
            timeout_seconds=self.timeout_seconds,
        )

    def _ensure_payload_indexes(self) -> None:
        for field_name, field_schema in PAYLOAD_INDEXES:
            try:
                request_json(
                    self.base_url,
                    f"{self._collection_path}/index",
                    service="qdrant",
                    method="PUT",
                    payload={"field_name": field_name, "field_schema": field_schema},
                    timeout_seconds=self.timeout_seconds,
                )
            except ServiceRequestError as exc:
                if exc.status_code != 409:
                    raise


def _validated_mode(payload: dict[str, Any], vector_size: int) -> str:
    mode = collection_mode(payload, vector_size)
    if mode:
        return mode
    raise ServiceRequestError(
        "qdrant",
        f"collection vector schema does not match embedding size {vector_size}; found {collection_vector_size(payload)}",
        409,
    )


def point_for_collection_mode(point: dict[str, Any], mode: str | None) -> dict[str, Any]:
    if mode != LEGACY_DENSE_MODE:
        return point
    vector = point.get("vector")
    dense = vector.get(DENSE_VECTOR_NAME) if isinstance(vector, dict) else None
    if not isinstance(dense, list):
        raise ValueError("legacy dense collection requires a dense vector")
    return {
        "id": point["id"],
        "vector": dense,
        "payload": point["payload"],
    }


def _with_current_status(point: dict[str, Any], is_current: bool) -> dict[str, Any]:
    payload = point.get("payload")
    return {
        **point,
        "payload": {
            **(payload if isinstance(payload, dict) else {}),
            "is_current": is_current,
        },
    }


def scroll_payload(doc_id: str, offset: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
        "limit": 256,
        "with_payload": True,
        "with_vector": False,
    }
    if offset is not None:
        payload["offset"] = offset
    return payload
