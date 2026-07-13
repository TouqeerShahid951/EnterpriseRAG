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
