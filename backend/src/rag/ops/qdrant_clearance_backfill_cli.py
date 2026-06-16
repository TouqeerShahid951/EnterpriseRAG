"""Backfill Qdrant clearance payload fields from PostgreSQL documents."""

from __future__ import annotations

import argparse
from typing import Any
from urllib.parse import quote

from rag.core.config import settings
from rag.query.http import request_json
from rag.repositories.postgres import PostgresConnectionMixin
from rag.shared.contracts.clearance import clearance_rank, normalize_clearance_level
from rag.shared.contracts.group_paths import normalize_group_path


class _Postgres(PostgresConnectionMixin):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url


def main() -> None:
    args = _parse_args()
    docs = _load_documents()
    collection_path = f"/collections/{quote(args.collection, safe='')}"
    scanned = 0
    updated = 0
    for point in _scroll_points(args.qdrant_url, collection_path, args.timeout_seconds):
        scanned += 1
        payload = point.get("payload")
        point_id = point.get("id")
        if not isinstance(payload, dict) or not point_id:
            continue
        doc = docs.get(str(payload.get("doc_id") or ""))
        if not doc:
            continue
        patch = _patch_for(payload, doc)
        if not patch:
            continue
        updated += 1
        if args.confirm:
            _set_payload(args.qdrant_url, collection_path, str(point_id), patch, args.timeout_seconds)
    print(f"documents={len(docs)}")
    print(f"points_scanned={scanned}")
    print(f"points_to_update={updated}")
    print(f"updated={updated if args.confirm else 0}")
    if not args.confirm:
        print("dry_run=true")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default=settings.qdrant_url)
    parser.add_argument("--collection", default=settings.qdrant_collection)
    parser.add_argument("--timeout-seconds", type=float, default=settings.rag_http_timeout_seconds)
    parser.add_argument("--confirm", action="store_true")
    return parser.parse_args()


def _load_documents() -> dict[str, dict[str, object]]:
    with _Postgres(settings.database_url)._connect() as conn:
        rows = conn.execute(
            """
            SELECT id::text id, group_path, clearance_level
            FROM documents
            WHERE deleted_at IS NULL
            """
        ).fetchall()
    return {
        str(row["id"]): {
            "group_path": normalize_group_path(str(row["group_path"])),
            "clearance_level": normalize_clearance_level(str(row["clearance_level"])),
        }
        for row in rows
    }


def _patch_for(payload: dict[str, Any], doc: dict[str, object]) -> dict[str, object]:
    group_path = str(doc["group_path"])
    clearance_level = str(doc["clearance_level"])
    desired = {
        "group_path": group_path,
        "acl_group_paths": [group_path],
        "clearance_level": clearance_level,
        "clearance_rank": clearance_rank(clearance_level),
    }
    return {
        key: value
        for key, value in desired.items()
        if payload.get(key) != value
    }


def _scroll_points(qdrant_url: str, collection_path: str, timeout_seconds: float) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    offset: Any = None
    while True:
        payload: dict[str, object] = {"limit": 256, "with_payload": True, "with_vector": False}
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
            raise RuntimeError("qdrant scroll response did not include points")
        points.extend(result["points"])
        offset = result.get("next_page_offset")
        if offset is None:
            return points


def _set_payload(
    qdrant_url: str,
    collection_path: str,
    point_id: str,
    payload: dict[str, object],
    timeout_seconds: float,
) -> None:
    request_json(
        qdrant_url,
        f"{collection_path}/points/payload?wait=true",
        service="qdrant",
        method="POST",
        payload={"payload": payload, "points": [point_id]},
        timeout_seconds=timeout_seconds,
    )


if __name__ == "__main__":
    main()
