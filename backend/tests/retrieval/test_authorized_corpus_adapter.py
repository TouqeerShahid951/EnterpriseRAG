from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from types import SimpleNamespace

import pytest

from rag.auth.context import UserContext
from rag.core.config import Settings
from rag.query.qdrant import SearchHit
from rag.query.configuration.models import RagConfigRecord
from rag.retrieval.adapters import query_runtime
from rag.retrieval.adapters.query_runtime import (
    QueryRuntimeAuthorizedCorpusRetriever,
)
from rag.retrieval.contracts import AuthorizedCorpusRequest, RetrievedChunk


def test_search_maps_scope_and_preserves_routing_and_reranking_policy(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    query_hit = SearchHit(
        point_id="point-1",
        score=0.73,
        payload={
            "doc_id": "doc-1",
            "doc_title": "Policy.pdf",
            "chunk_id": "chunk-1",
            "page_start": 2,
            "page_end": 3,
            "chunk_type": "table",
            "text": "  Policy   finding  ",
            "structured_fields": [
                {"label": "Owner", "value": "Risk"},
                {"label": "", "value": "ignored"},
            ],
            "_rerank_score": 0.91,
            "chunk_content_hash": "content-sha",
            "text_hash": "text-sha",
        },
    )
    ctx: dict[str, object] = {}

    def initial_retrieval_state(**kwargs):
        captured["initial"] = kwargs
        return ctx

    route_plan = SimpleNamespace(public_intent="aggregation", top_k=50)

    def route_query(query, **kwargs):
        captured["route"] = (query, kwargs)
        return route_plan, object()

    def retrieve_candidates(received_ctx, **kwargs):
        captured["retrieve"] = (received_ctx, kwargs)
        return [query_hit]

    def rerank_hits(query, hits, **kwargs):
        captured["rerank"] = (query, hits, kwargs)
        return hits

    monkeypatch.setattr(
        query_runtime, "initial_retrieval_state", initial_retrieval_state
    )
    monkeypatch.setattr(query_runtime, "route_query", route_query)
    monkeypatch.setattr(query_runtime, "retrieve_candidates", retrieve_candidates)
    monkeypatch.setattr(query_runtime, "rerank_hits", rerank_hits)
    config = Settings(
        document_repository="memory",
        rag_top_k=3,
        rag_reranker_max_candidates=40,
        artifact_reranker_max_candidates=12,
        rag_reranker_cache_dir="/models/test-reranker",
    )
    rag_config = _rag_config(
        retrieval_token_budget=6789, reranker_model="test-reranker"
    )
    inference = object()
    qdrant = object()
    retriever = QueryRuntimeAuthorizedCorpusRetriever(
        config=config,
        rag_config=rag_config,
        inference=inference,  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )
    request = _request(
        query="policy finding",
        group_path="/finance",
        document_ids=("doc-2", "doc-1"),
    )

    result = retriever.search(request)

    assert captured["initial"] == {
        "trace_id": "trace-1",
        "session_id": "session-1",
        "query": "policy finding",
        "group_path": "/finance",
        "document_ids": ("doc-2", "doc-1"),
        "user": UserContext(
            user_id="user-1",
            email="user@example.test",
            account_type="platform_admin",
            group_paths=("/finance",),
            clearance_level="NATO_CONFIDENTIAL",
            permission_version=4,
        ),
        "token_budget": 6789,
    }
    route_query_text, route_kwargs = captured["route"]  # type: ignore[misc]
    assert route_query_text == "policy finding"
    assert route_kwargs == {
        "turns": [],
        "base_top_k": 8,
        "llm_verifier": None,
        "verifier_model": None,
        "verifier_enabled": False,
    }
    received_ctx, retrieve_kwargs = captured["retrieve"]  # type: ignore[misc]
    assert received_ctx is ctx
    assert retrieve_kwargs == {
        "config": config,
        "ollama": inference,
        "qdrant": qdrant,
    }
    assert ctx == {
        "route_plan": route_plan,
        "intent": "aggregation",
        "sub_queries": ["policy finding"],
        "is_current_only": True,
    }
    rerank_query, rerank_input, rerank_kwargs = captured["rerank"]  # type: ignore[misc]
    assert rerank_query == "policy finding"
    assert rerank_input == [query_hit]
    assert rerank_kwargs == {
        "top_k": 12,
        "max_candidates": 12,
        "model_name": "test-reranker",
        "cache_dir": "/models/test-reranker",
    }
    normalized_text = "policy finding"
    assert result == (
        RetrievedChunk(
            point_id="point-1",
            doc_id="doc-1",
            doc_title="Policy.pdf",
            chunk_id="chunk-1",
            page_start=2,
            page_end=3,
            content_type="table",
            text="  Policy   finding  ",
            structured_fields=(("Owner", "Risk"),),
            retrieval_score=0.73,
            rerank_score=0.91,
            identity_keys=frozenset(
                {
                    "chunk:chunk-1",
                    f"text:{sha256(normalized_text.encode()).hexdigest()}",
                    "chunk_content_hash:content-sha",
                    "text_hash:text-sha",
                }
            ),
        ),
    )


def test_document_scan_applies_group_temporal_expiry_stale_and_document_scope() -> None:
    qdrant = _CapturingQdrant(
        hits=[
            SearchHit(
                point_id="point-1",
                score=0.5,
                payload={
                    "doc_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "structured_kind": "table_row",
                    "structured_fields": [{"label": "Status", "value": "Open"}],
                },
            )
        ]
    )
    retriever = _retriever(qdrant=qdrant)

    result = retriever.scan_documents(
        _request(
            query="policy status in 2024",
            group_path="/finance",
            document_ids=("doc-2", "doc-1"),
        ),
        structured_only=True,
        limit=4000,
    )

    assert qdrant.calls[0]["document_ids"] == ["doc-2", "doc-1"]
    assert qdrant.calls[0]["structured_only"] is True
    assert qdrant.calls[0]["limit"] == 4000
    qdrant_filter = qdrant.calls[0]["qdrant_filter"]
    assert isinstance(qdrant_filter, dict)
    must = qdrant_filter["must"]
    assert isinstance(must, list)
    assert must[0] == {
        "should": [
            {"key": "acl_group_paths", "match": {"value": "/finance"}},
            {"key": "group_path", "match": {"value": "/finance"}},
        ]
    }
    assert {"key": "is_current", "match": {"value": True}} not in must
    assert {
        "should": [
            {"key": "effective_date", "range": {"lte": "2024-12-31"}},
            {"is_empty": {"key": "effective_date"}},
        ]
    } in must
    assert {
        "should": [
            {"key": "is_expired", "match": {"value": False}},
            {"is_empty": {"key": "is_expired"}},
        ]
    } in must
    assert {
        "must": [
            {
                "should": [
                    {"key": "source_deleted", "match": {"value": False}},
                    {"is_empty": {"key": "source_deleted"}},
                ]
            },
            {
                "should": [
                    {"key": "retrieval_status", "match": {"value": "active"}},
                    {"is_empty": {"key": "retrieval_status"}},
                ]
            },
        ]
    } in must
    assert must[-1] == {
        "should": [
            {"key": "doc_id", "match": {"value": "doc-1"}},
            {"key": "doc_id", "match": {"value": "doc-2"}},
        ]
    }
    assert result[0].doc_title == "Untitled"
    assert result[0].content_type == "table_row"
    assert result[0].structured_fields == (("Status", "Open"),)


def test_document_scan_uses_current_scope_when_query_has_no_date() -> None:
    qdrant = _CapturingQdrant(hits=[])
    retriever = _retriever(qdrant=qdrant)

    retriever.scan_documents(
        _request(query="current policy", document_ids=("doc-1",)),
        structured_only=False,
        limit=10,
    )

    qdrant_filter = qdrant.calls[0]["qdrant_filter"]
    assert isinstance(qdrant_filter, dict)
    assert {"key": "is_current", "match": {"value": True}} in qdrant_filter["must"]


def test_document_scan_rejects_group_scope_outside_user_authorization() -> None:
    qdrant = _CapturingQdrant(hits=[])
    retriever = _retriever(qdrant=qdrant)

    with pytest.raises(
        PermissionError,
        match="requested group path is outside the authorized corpus scope",
    ):
        retriever.scan_documents(
            _request(group_path="/legal"),
            structured_only=False,
            limit=10,
        )

    assert qdrant.calls == []


def test_search_propagates_query_runtime_failures(monkeypatch) -> None:
    ctx: dict[str, object] = {}
    monkeypatch.setattr(query_runtime, "initial_retrieval_state", lambda **_kwargs: ctx)
    monkeypatch.setattr(
        query_runtime,
        "route_query",
        lambda *_args, **_kwargs: (
            SimpleNamespace(public_intent="factual_simple", top_k=8),
            object(),
        ),
    )
    failure = RuntimeError("vector retrieval unavailable")

    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(query_runtime, "retrieve_candidates", fail)

    with pytest.raises(RuntimeError) as raised:
        _retriever(qdrant=object()).search(_request())

    assert raised.value is failure


def test_document_scan_rejects_invalid_limit_and_propagates_storage_failure() -> None:
    failure = RuntimeError("qdrant unavailable")
    qdrant = _CapturingQdrant(failure=failure)
    retriever = _retriever(qdrant=qdrant)

    with pytest.raises(ValueError, match="document scan limit must be positive"):
        retriever.scan_documents(_request(), structured_only=False, limit=0)
    with pytest.raises(RuntimeError) as raised:
        retriever.scan_documents(_request(), structured_only=False, limit=1)

    assert raised.value is failure


def test_boundary_values_are_immutable_and_normalize_nested_collections() -> None:
    request = AuthorizedCorpusRequest(
        trace_id="trace-1",
        session_id="session-1",
        query="policy",
        user=_user(),
        group_path=None,
        document_ids=["doc-1"],  # type: ignore[arg-type]
    )
    chunk = RetrievedChunk(
        point_id="point-1",
        doc_id="doc-1",
        doc_title="Policy.pdf",
        chunk_id="chunk-1",
        page_start=None,
        page_end=None,
        content_type="text",
        text="policy",
        structured_fields=[["Owner", "Risk"]],  # type: ignore[list-item]
        retrieval_score=0.5,
        rerank_score=None,
        identity_keys={"chunk:chunk-1"},  # type: ignore[arg-type]
    )

    assert request.document_ids == ("doc-1",)
    assert chunk.structured_fields == (("Owner", "Risk"),)
    assert chunk.identity_keys == frozenset(
        {
            "chunk:chunk-1",
            f"text:{sha256('policy'.encode()).hexdigest()}",
        }
    )
    with pytest.raises(FrozenInstanceError):
        request.query = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        chunk.text = "changed"  # type: ignore[misc]


class _CapturingQdrant:
    def __init__(
        self,
        *,
        hits: list[SearchHit] | None = None,
        failure: RuntimeError | None = None,
    ) -> None:
        self.hits = hits or []
        self.failure = failure
        self.calls: list[dict[str, object]] = []

    def retrieve_document_chunks(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return self.hits


def _retriever(*, qdrant: object) -> QueryRuntimeAuthorizedCorpusRetriever:
    return QueryRuntimeAuthorizedCorpusRetriever(
        config=Settings(document_repository="memory"),
        rag_config=_rag_config(),
        inference=object(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )


def _request(
    *,
    query: str = "policy",
    group_path: str | None = None,
    document_ids: tuple[str, ...] = ("doc-1",),
) -> AuthorizedCorpusRequest:
    return AuthorizedCorpusRequest(
        trace_id="trace-1",
        session_id="session-1",
        query=query,
        user=_user(),
        group_path=group_path,
        document_ids=document_ids,
    )


def _user() -> UserContext:
    return UserContext(
        user_id="user-1",
        email="user@example.test",
        account_type="platform_admin",
        group_paths=("/finance", "/operations"),
        clearance_level="NATO_CONFIDENTIAL",
        permission_version=4,
    )


def _rag_config(
    *,
    retrieval_token_budget: int = 12000,
    reranker_model: str = "jinaai/jina-reranker-v1-turbo-en",
) -> RagConfigRecord:
    return RagConfigRecord(
        base_url="http://example.test",
        chat_model="test-chat",
        embed_model="test-embed",
        faithfulness_model=None,
        chat_timeout_seconds=1,
        embed_timeout_seconds=1,
        retrieval_token_budget=retrieval_token_budget,
        reranker_model=reranker_model,
    )
