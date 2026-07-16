from __future__ import annotations

from rag.query import qdrant as qdrant_module
from rag.query.qdrant import QdrantClient


def test_document_scan_enforces_document_ids_in_the_storage_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def request_json(_base_url: str, _path: str, **kwargs):
        captured.update(kwargs)
        return {"result": {"points": [], "next_page_offset": None}}

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
    )

    assert (
        client.retrieve_document_chunks(
            document_ids=[" doc-2 ", "doc-1", "doc-2", ""],
            qdrant_filter={
                "must": [{"key": "group_path", "match": {"value": "/finance"}}]
            },
            structured_only=True,
            limit=10,
        )
        == []
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    must = payload["filter"]["must"]
    assert must[0] == {"key": "group_path", "match": {"value": "/finance"}}
    assert must[1] == {
        "should": [
            {"key": "doc_id", "match": {"value": "doc-1"}},
            {"key": "doc_id", "match": {"value": "doc-2"}},
        ]
    }
    assert must[2] == {
        "should": [
            {"key": "chunk_type", "match": {"value": "table_row"}},
            {"key": "structured_kind", "match": {"value": "table_row"}},
            {"key": "structured_kind", "match": {"value": "kv_record"}},
        ]
    }


def test_document_scan_with_no_document_ids_fails_closed_without_storage_io(
    monkeypatch,
) -> None:
    called = False

    def request_json(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"result": {"points": [], "next_page_offset": None}}

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
    )

    assert (
        client.retrieve_document_chunks(
            document_ids=[],
            qdrant_filter={},
            structured_only=False,
            limit=10,
        )
        == []
    )
    assert called is False


def test_authorized_scan_preserves_filter_and_reports_truncation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def request_json(_base_url: str, _path: str, **kwargs):
        captured.update(kwargs)
        return {
            "result": {
                "points": [
                    {"id": "one", "payload": {"doc_id": "doc"}},
                    {"id": "two", "payload": {"doc_id": "doc"}},
                ],
                "next_page_offset": "more",
            }
        }

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
    )
    qdrant_filter = {
        "must": [
            {"key": "group_paths", "match": {"any": ["/finance"]}},
            {"key": "clearance_rank", "range": {"lte": 20}},
            {"key": "is_current", "match": {"value": True}},
            {"key": "is_expired", "match": {"value": False}},
            {"key": "source_deleted", "match": {"value": False}},
        ]
    }

    hits = client.retrieve_authorized_chunks(
        qdrant_filter=qdrant_filter,
        structured_only=False,
        limit=1,
    )

    assert captured["payload"]["filter"] == qdrant_filter
    assert captured["payload"]["limit"] == 2
    assert len(hits) == 1
    assert hits[0].payload["authorized_scan_complete"] is False


def test_expired_document_scan_deadline_avoids_storage_io(monkeypatch) -> None:
    called = False

    def request_json(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"result": {"points": [], "next_page_offset": None}}

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=30,
    )

    hits = client.retrieve_document_chunks(
        document_ids=["doc"],
        qdrant_filter={},
        structured_only=False,
        limit=10,
        deadline=0.0,
    )

    assert hits == []
    assert called is False


def test_generation_fence_returns_only_the_active_published_points(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def request_json(_base_url: str, _path: str, **kwargs):
        captured.update(kwargs)
        return {
            "result": [
                _point("stale", "doc-a", generation="old", published=True),
                _point("building", "doc-a", generation="new", published=False),
                _point("active", "doc-a", generation="new", published=True),
                _point("legacy", "doc-b"),
            ]
        }

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
        active_generation_resolver=lambda _ids, _current_only: {
            "doc-a": "new",
            "doc-b": None,
        },
    )

    hits = client.search([0.1], limit=2, qdrant_filter={})

    assert [hit.point_id for hit in hits] == ["active", "legacy"]
    assert captured["payload"]["limit"] == 8


def test_ranked_search_refills_beyond_stale_generation_hits(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    def request_json(_base_url: str, _path: str, **kwargs):
        payload = kwargs["payload"]
        requests.append(payload)
        if payload.get("offset", 0) == 0:
            return {
                "result": [
                    _point(f"stale-{index}", "doc-a", generation="old", published=True)
                    for index in range(4)
                ]
            }
        return {"result": [_point("active", "doc-a", generation="new", published=True)]}

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
        active_generation_resolver=lambda _ids, _current_only: {"doc-a": "new"},
    )

    hits = client.search([0.1], limit=1, qdrant_filter={})

    assert [hit.point_id for hit in hits] == ["active"]
    assert requests[0]["limit"] == 4
    assert requests[1]["offset"] == 4


def test_generation_fence_keeps_historical_document_generations(monkeypatch) -> None:
    resolver_calls: list[bool] = []

    def request_json(_base_url: str, _path: str, **_kwargs):
        return {"result": [_point("historical", "doc-a", generation="old", published=True)]}

    def resolve(_ids: list[str], current_only: bool) -> dict[str, str | None]:
        resolver_calls.append(current_only)
        return {"doc-a": "old"} if not current_only else {}

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
        active_generation_resolver=resolve,
    )

    assert client.search(
        [0.1],
        limit=1,
        qdrant_filter={"must": [{"key": "is_current", "match": {"value": True}}]},
    ) == []
    assert [hit.point_id for hit in client.search([0.1], limit=1, qdrant_filter={})] == [
        "historical"
    ]
    assert resolver_calls == [True, False]


def test_document_scan_refills_after_a_page_of_stale_generations(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    def request_json(_base_url: str, _path: str, **kwargs):
        requests.append(kwargs["payload"])
        if len(requests) == 1:
            return {
                "result": {
                    "points": [_point("stale", "doc-a", generation="old", published=True)],
                    "next_page_offset": "next",
                }
            }
        return {
            "result": {
                "points": [_point("active", "doc-a", generation="new", published=True)],
                "next_page_offset": None,
            }
        }

    monkeypatch.setattr(qdrant_module, "request_json", request_json)
    client = QdrantClient(
        base_url="http://qdrant.test",
        collection="documents",
        timeout_seconds=1,
        active_generation_resolver=lambda _ids, _current_only: {"doc-a": "new"},
    )

    hits = client.retrieve_document_chunks(
        document_ids=["doc-a"],
        qdrant_filter={},
        structured_only=False,
        limit=1,
    )

    assert [hit.point_id for hit in hits] == ["active"]
    assert len(requests) == 2
    assert requests[1]["offset"] == "next"


def _point(
    point_id: str,
    document_id: str,
    *,
    generation: str | None = None,
    published: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"doc_id": document_id}
    if generation is not None:
        payload["index_generation_id"] = generation
    if published is not None:
        payload["generation_published"] = published
    return {"id": point_id, "score": 1.0, "payload": payload}
