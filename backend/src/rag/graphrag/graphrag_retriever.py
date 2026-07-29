"""Query-time GraphRAG community-summary retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rag.auth.abac import build_abac_filter
from rag.query.cancellation import call_with_optional_cancellation, cancellation_token_from_context
from rag.query.qdrant import QdrantClient, SearchHit
from rag.query.retrieval.query_retrieval import add_document_scope
from rag.query.state import QueryContext, scoped_user_context

from .models import CommunitySummary, SourceRef
from .qdrant import CommunitySearchHit, QdrantGraphRAGClient, QdrantGraphRAGError


@dataclass(frozen=True)
class GraphRAGRetrievalResult:
    communities: list[CommunitySearchHit]
    source_hits: list[SearchHit]
    degraded_reason: str | None = None

    @property
    def is_available(self) -> bool:
        return bool(self.communities and self.source_hits and not self.degraded_reason)


class GraphRAGRetriever:
    def __init__(
        self,
        *,
        config: Any,
        embedder: Any,
        document_qdrant: QdrantClient,
        community_qdrant: QdrantGraphRAGClient | None = None,
    ) -> None:
        self.config = config
        self.embedder = embedder
        self.document_qdrant = document_qdrant
        self.community_qdrant = community_qdrant or QdrantGraphRAGClient(
            base_url=config.qdrant_url,
            documents_collection=config.qdrant_collection,
            community_collection=config.graphrag_community_collection,
            timeout_seconds=config.rag_http_timeout_seconds,
        )

    def retrieve(self, ctx: QueryContext, *, top_k_communities: int = 8) -> GraphRAGRetrievalResult:
        if not getattr(self.config, "graphrag_enabled", False):
            return GraphRAGRetrievalResult([], [], "graphrag_disabled")
        plan = ctx.get("route_plan")
        query = plan.resolved_query if plan is not None else ctx["request"].query
        cancellation_token = cancellation_token_from_context(ctx)
        try:
            vector = call_with_optional_cancellation(self.embedder.embed, cancellation_token, query)
            community_filter = _community_filter(ctx)
            community_hits = self.community_qdrant.search_summaries(
                vector=vector,
                qdrant_filter=community_filter,
                limit=top_k_communities,
            )
        except QdrantGraphRAGError as exc:
            return GraphRAGRetrievalResult([], [], f"graphrag_summary_search_unavailable: {str(exc)[:240]}")
        except Exception as exc:
            return GraphRAGRetrievalResult([], [], f"graphrag_retrieval_failed: {str(exc)[:240]}")
        if not community_hits:
            return GraphRAGRetrievalResult([], [], "graphrag_no_community_summaries")
        community_hits = _document_scoped_communities(
            community_hits,
            ctx["request"].document_ids,
        )
        if not community_hits:
            return GraphRAGRetrievalResult(
                [],
                [],
                "graphrag_no_scope_safe_community_summaries",
            )
        refs = _source_refs([hit.summary for hit in community_hits])
        if not refs:
            return GraphRAGRetrievalResult(community_hits, [], "graphrag_summaries_missing_sources")
        source_filter = add_document_scope(
            build_abac_filter(scoped_user_context(ctx), is_current_only=ctx["is_current_only"]),
            ctx["request"].document_ids,
        )
        try:
            source_hits = self.document_qdrant.retrieve_chunks(
                [(ref.doc_id, ref.chunk_id) for ref in refs],
                qdrant_filter=source_filter,
                cancellation_token=cancellation_token,
            )
        except Exception as exc:
            return GraphRAGRetrievalResult(community_hits, [], f"graphrag_source_retrieval_failed: {str(exc)[:240]}")
        if not source_hits:
            return GraphRAGRetrievalResult(community_hits, [], "graphrag_no_authorized_source_chunks")
        return GraphRAGRetrievalResult(community_hits, source_hits)


def _community_filter(ctx: QueryContext) -> dict[str, Any]:
    qdrant_filter = build_abac_filter(scoped_user_context(ctx), is_current_only=ctx["is_current_only"])
    document_ids = sorted({doc_id.strip() for doc_id in ctx["request"].document_ids if doc_id.strip()})
    if not document_ids:
        return qdrant_filter
    scoped = dict(qdrant_filter)
    must = list(scoped.get("must", []))
    must.append(
        {
            "should": [
                {"key": "source_doc_ids", "match": {"value": doc_id}}
                for doc_id in document_ids
            ]
        }
    )
    scoped["must"] = must
    return scoped


def _source_refs(summaries: list[CommunitySummary]) -> list[SourceRef]:
    seen: set[tuple[str, str]] = set()
    refs: list[SourceRef] = []
    for summary in summaries:
        for ref in summary.source_refs:
            key = (ref.doc_id, ref.chunk_id)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs


def _document_scoped_communities(
    communities: list[CommunitySearchHit],
    document_ids: list[str],
) -> list[CommunitySearchHit]:
    scoped_ids = {doc_id.strip() for doc_id in document_ids if doc_id.strip()}
    if not scoped_ids:
        return communities
    return [
        hit
        for hit in communities
        if hit.summary.source_refs
        and {ref.doc_id for ref in hit.summary.source_refs}.issubset(scoped_ids)
    ]
