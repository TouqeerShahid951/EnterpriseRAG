"""Qdrant payload repair utilities for reindex operations."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..query.http import ServiceRequestError, request_json


def mark_documents_not_current(
    *,
    qdrant_url: str,
    collection: str,
    doc_ids: list[str],
    timeout_seconds: float,
) -> int:
    updated = 0
    collection_path = f"/collections/{quote(collection, safe='')}"
    for doc_id in doc_ids:
        for point in _document_points(qdrant_url, collection_path, doc_id, timeout_seconds):
            point_id = point.get("id")
            payload = point.get("payload")
            if not point_id or not isinstance(payload, dict):
                raise ServiceRequestError("qdrant", "scroll response contained an invalid point", 502)
            _set_payload(qdrant_url, collection_path, str(point_id), {**payload, "is_current": False}, timeout_seconds)
            updated += 1
    return updated


def _document_points(
    qdrant_url: str,
    collection_path: str,
    doc_id: str,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    offset: Any = None
    while True:
        payload: dict[str, Any] = {
            "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
            "limit": 256,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            payload["offset"] = offset
        response = request_json(
            qdrant_url,
            f"{collection_path}/points/scroll",
            service="qdrant",
            method="POST",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list):
            raise ServiceRequestError("qdrant", "scroll response did not include points", 502)
        points.extend(result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            return points


def _set_payload(
    qdrant_url: str,
    collection_path: str,
    point_id: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> None:
    request_json(
        qdrant_url,
        f"{collection_path}/points/payload?wait=true",
        service="qdrant",
        method="PUT",
        payload={"payload": payload, "points": [point_id]},
        timeout_seconds=timeout_seconds,
    )
