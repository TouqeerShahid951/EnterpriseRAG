"""Authorized corpus retrieval backed by the current query runtime."""

from __future__ import annotations

from hashlib import sha256

from ...auth.abac import build_abac_filter
from ...auth.context import UserContext
from ...core.config import Settings
from ...query.inference import InferenceClient
from rag.query.routing.intent_router import route_query
from ...query.qdrant import QdrantClient, SearchHit
from rag.query.retrieval.query_retrieval import (
    add_document_scope,
    add_expiry_scope,
    add_stale_scope,
    retrieve_candidates,
)
from ...query.configuration.models import RagConfigRecord
from ...query.reranker import rerank_hits
from ...query.state import initial_retrieval_state
from rag.query.retrieval.temporal import add_effective_date_scope, target_date_for_query
from ...shared.contracts.group_paths import normalize_group_path
from ..contracts import AuthorizedCorpusRequest, RetrievedChunk


class QueryRuntimeAuthorizedCorpusRetriever:
    def __init__(
        self,
        *,
        config: Settings,
        rag_config: RagConfigRecord,
        inference: InferenceClient,
        qdrant: QdrantClient,
    ) -> None:
        self._config = config
        self._rag_config = rag_config
        self._inference = inference
        self._qdrant = qdrant

    def search(self, request: AuthorizedCorpusRequest) -> tuple[RetrievedChunk, ...]:
        user = _scoped_user(request.user, request.group_path)
        ctx = initial_retrieval_state(
            trace_id=request.trace_id,
            session_id=request.session_id,
            query=request.query,
            group_path=request.group_path,
            document_ids=request.document_ids,
            user=user,
            token_budget=self._rag_config.retrieval_token_budget,
        )
        route_plan, _signals = route_query(
            request.query,
            turns=[],
            base_top_k=max(self._config.rag_top_k, 8),
            llm_verifier=None,
            verifier_model=None,
            verifier_enabled=False,
        )
        ctx["route_plan"] = route_plan
        ctx["intent"] = route_plan.public_intent
        ctx["sub_queries"] = [request.query]
        ctx["is_current_only"] = target_date_for_query(request.query) is None
        hits = retrieve_candidates(
            ctx,
            config=self._config,
            ollama=self._inference,
            qdrant=self._qdrant,
        )
        max_candidates = min(
            self._config.rag_reranker_max_candidates,
            self._config.artifact_reranker_max_candidates,
        )
        reranked = rerank_hits(
            request.query,
            hits,
            top_k=min(max(route_plan.top_k, 8), max_candidates),
            max_candidates=max_candidates,
            model_name=self._rag_config.reranker_model,
            cache_dir=self._config.rag_reranker_cache_dir,
        )
        return tuple(_retrieved_chunk(hit) for hit in reranked)

    def scan_documents(
        self,
        request: AuthorizedCorpusRequest,
        *,
        structured_only: bool,
        limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        if limit <= 0:
            raise ValueError("document scan limit must be positive")
        qdrant_filter = _authorized_filter(request, config=self._config)
        hits = self._qdrant.retrieve_document_chunks(
            document_ids=list(request.document_ids),
            qdrant_filter=qdrant_filter,
            structured_only=structured_only,
            limit=limit,
        )
        return tuple(_retrieved_chunk(hit) for hit in hits)


def _authorized_filter(
    request: AuthorizedCorpusRequest,
    *,
    config: Settings,
) -> dict[str, object]:
    target_date = target_date_for_query(request.query)
    user = _scoped_user(request.user, request.group_path)
    qdrant_filter = build_abac_filter(user, is_current_only=target_date is None)
    qdrant_filter = add_effective_date_scope(qdrant_filter, target_date)
    qdrant_filter = add_expiry_scope(qdrant_filter)
    if not config.connector_include_stale_in_retrieval:
        qdrant_filter = add_stale_scope(qdrant_filter)
    return add_document_scope(qdrant_filter, list(request.document_ids))


def _scoped_user(user: UserContext, group_path: str | None) -> UserContext:
    if not group_path:
        return user
    normalized_group_path = normalize_group_path(group_path)
    authorized_group_paths = {normalize_group_path(path) for path in user.group_paths}
    if normalized_group_path not in authorized_group_paths:
        raise PermissionError(
            "requested group path is outside the authorized corpus scope"
        )
    return UserContext(
        user_id=user.user_id,
        email=user.email,
        account_type=user.account_type,
        group_paths=(normalized_group_path,),
        clearance_level=user.clearance_level,
        permission_version=user.permission_version,
    )


def _retrieved_chunk(hit: SearchHit) -> RetrievedChunk:
    payload = hit.payload
    doc_id = str(payload.get("doc_id") or hit.point_id)
    chunk_id = str(payload.get("chunk_id") or hit.point_id)
    return RetrievedChunk(
        point_id=hit.point_id,
        doc_id=doc_id,
        doc_title=str(payload.get("doc_title") or "Untitled"),
        chunk_id=chunk_id,
        page_start=_int(payload.get("page_start")) or _int(payload.get("page")),
        page_end=(
            _int(payload.get("page_end"))
            or _int(payload.get("page_start"))
            or _int(payload.get("page"))
        ),
        content_type=str(
            payload.get("chunk_type") or payload.get("structured_kind") or "text"
        ),
        text=str(payload.get("text") or ""),
        structured_fields=_structured_fields(payload.get("structured_fields")),
        retrieval_score=float(hit.score),
        rerank_score=(
            float(payload["_rerank_score"])
            if isinstance(payload.get("_rerank_score"), int | float)
            else None
        ),
        identity_keys=_identity_keys(hit),
    )


def _structured_fields(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        (str(item["label"]), str(item["value"]))
        for item in value
        if isinstance(item, dict) and item.get("label") and item.get("value")
    )


def _identity_keys(hit: SearchHit) -> frozenset[str]:
    chunk_id = hit.payload.get("chunk_id") or hit.point_id
    keys = {f"chunk:{chunk_id}"}
    raw_text = hit.payload.get("text")
    text = raw_text.strip() if isinstance(raw_text, str) else ""
    if text:
        normalized = " ".join(text.lower().split())
        keys.add(f"text:{sha256(normalized.encode()).hexdigest()}")
    for field in ("chunk_content_hash", "text_hash"):
        value = hit.payload.get(field)
        if isinstance(value, str) and value:
            keys.add(f"{field}:{value}")
    return frozenset(keys)


def _int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None
