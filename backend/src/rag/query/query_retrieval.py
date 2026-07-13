"""ABAC-constrained retrieval orchestration and compatibility facade."""

from __future__ import annotations

from ..auth.abac import build_abac_filter
from ..core.config import Settings
from .cancellation import (
    call_with_optional_cancellation,
    cancellation_token_from_context,
)
from .inference import InferenceClient
from .metadata_scoring import metadata_boost_hits
from .qdrant import QdrantClient, SearchHit
from .retrieval_document_scope import (
    _document_metadata_tokens,
    _document_scope_focus_tokens,
    _document_scope_hits,
    _document_scope_sort_key,
    _document_scope_token_groups,
    _documents_matching_scope_tokens,
    _focused_document_scope_hits,
    _has_broad_document_scope,
    _mark_document_scope_hit,
    _metadata_tokens_by_doc,
    _round_robin_document_hits,
    _scope_tokens,
    _should_expand_document_scope,
    _target_document_ids_for_scope,
)
from .retrieval_hits import (
    _doc_ids,
    _hit_doc_id,
    _hit_focus_parts,
    _hit_focus_text,
    _hit_focus_tokens,
    _optional_int,
)
from .retrieval_policy import (
    _base_search_limit_multiplier,
    _has_claim_evidence,
    _has_source_metadata,
    _order_by_parent_section,
    _parent_key,
    _parent_section_sort_key,
    _promote_hits,
    _search_limit_multiplier,
    _search_query,
    _target_date_from_plan,
    add_document_scope,
    add_expiry_scope,
    add_stale_scope,
    apply_route_retrieval_policy,
    merge_artifact_protected_hits,
    merge_route_protected_hits,
    not_expired_condition,
    not_stale_condition,
    prioritize_language,
    query_language,
    route_protected_hits,
)
from .retrieval_recall import (
    _annotate_recall_hits,
    _definition_cue_near_target,
    _definition_target,
    _has_definition_evidence,
    _ordered_recall_tokens,
    _recall_context_terms,
    _recall_expansion_queries,
    _target_variants,
    _unique_nonempty,
)
from .retrieval_structured import (
    _annotate_structured_hits,
    _artifact_requires_structured_rows,
    _has_structured_evidence,
    _has_table_evidence,
    _has_table_row_lookup_signal,
    _has_table_superlative_signal,
    _promote_structured_matches,
    _should_expand_structured_rows,
    _should_use_structured_path,
    _sort_table_rows,
    _structured_field_match_score,
    _table_key,
    expand_structured_table_rows,
)
from .sources import dedupe_hits
from .state import QueryContext, scoped_user_context
from .temporal import add_effective_date_scope

_DOCUMENT_SCOPE_SCAN_LIMIT = 5000

__all__ = [
    "_annotate_recall_hits",
    "_annotate_structured_hits",
    "_artifact_requires_structured_rows",
    "_base_search_limit_multiplier",
    "_definition_cue_near_target",
    "_definition_target",
    "_doc_ids",
    "_document_metadata_tokens",
    "_document_scope_focus_tokens",
    "_document_scope_hits",
    "_document_scope_sort_key",
    "_document_scope_token_groups",
    "_documents_matching_scope_tokens",
    "_focused_document_scope_hits",
    "_has_broad_document_scope",
    "_has_claim_evidence",
    "_has_definition_evidence",
    "_has_source_metadata",
    "_has_structured_evidence",
    "_has_table_evidence",
    "_has_table_row_lookup_signal",
    "_has_table_superlative_signal",
    "_hit_doc_id",
    "_hit_focus_parts",
    "_hit_focus_text",
    "_hit_focus_tokens",
    "_mark_document_scope_hit",
    "_metadata_tokens_by_doc",
    "_optional_int",
    "_order_by_parent_section",
    "_ordered_recall_tokens",
    "_parent_key",
    "_parent_section_sort_key",
    "_promote_hits",
    "_promote_structured_matches",
    "_recall_context_terms",
    "_recall_expansion_queries",
    "_round_robin_document_hits",
    "_scope_tokens",
    "_search_limit_multiplier",
    "_search_query",
    "_should_expand_document_scope",
    "_should_expand_structured_rows",
    "_should_use_structured_path",
    "_sort_table_rows",
    "_structured_field_match_score",
    "_table_key",
    "_target_date_from_plan",
    "_target_document_ids_for_scope",
    "_target_variants",
    "_unique_nonempty",
    "add_document_scope",
    "add_expiry_scope",
    "add_stale_scope",
    "apply_route_retrieval_policy",
    "expand_structured_table_rows",
    "merge_artifact_protected_hits",
    "merge_route_protected_hits",
    "not_expired_condition",
    "not_stale_condition",
    "prioritize_language",
    "query_language",
    "retrieve_candidates",
    "route_protected_hits",
]


def retrieve_candidates(
    ctx: QueryContext,
    *,
    config: Settings,
    ollama: InferenceClient,
    qdrant: QdrantClient,
) -> list[SearchHit]:
    hits: list[SearchHit] = []
    cancellation_token = cancellation_token_from_context(ctx)
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    plan = ctx.get("route_plan")
    artifact_plan = ctx.get("artifact_plan")
    active_query = (
        ctx["query_rewritten"][-1]
        if ctx["query_rewritten"]
        else (plan.resolved_query if plan else ctx["request"].query)
    )
    top_k = plan.top_k if plan else config.rag_top_k
    search_limit = top_k * _search_limit_multiplier(plan, active_query)
    if _artifact_requires_structured_rows(artifact_plan):
        search_limit = max(search_limit, top_k * 16)
    qdrant_filter = add_effective_date_scope(
        build_abac_filter(
            scoped_user_context(ctx), is_current_only=ctx["is_current_only"]
        ),
        _target_date_from_plan(plan, active_query)
        if not ctx["is_current_only"]
        else None,
    )
    qdrant_filter = add_expiry_scope(qdrant_filter)
    if not getattr(config, "connector_include_stale_in_retrieval", False):
        qdrant_filter = add_stale_scope(qdrant_filter)
    qdrant_filter = add_document_scope(qdrant_filter, ctx["request"].document_ids)
    for query in ctx["sub_queries"] or [active_query]:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        dense_vector = call_with_optional_cancellation(
            ollama.embed, cancellation_token, query
        )
        if not call_with_optional_cancellation(
            qdrant.prepare_for_query, cancellation_token, len(dense_vector)
        ):
            continue
        hits.extend(
            _search_query(
                query,
                dense_vector=dense_vector,
                limit=search_limit,
                qdrant_filter=qdrant_filter,
                config=config,
                qdrant=qdrant,
                cancellation_token=cancellation_token,
            )
        )
    ranked = prioritize_language(dedupe_hits(hits), query_language(active_query))
    ranked = metadata_boost_hits(active_query, ranked)
    ranked = apply_route_retrieval_policy(ranked, plan)
    ranked = _annotate_structured_hits(ranked, origin="direct")
    if _artifact_requires_structured_rows(artifact_plan) or _should_use_structured_path(
        active_query, ranked, plan
    ):
        ranked = _promote_structured_matches(ranked, active_query)
        ranked = expand_structured_table_rows(
            ranked,
            qdrant=qdrant,
            qdrant_filter=qdrant_filter,
            cancellation_token=cancellation_token,
        )
    if _should_expand_document_scope(active_query, plan) and hasattr(
        qdrant, "retrieve_authorized_chunks"
    ):
        scope_hits = call_with_optional_cancellation(
            qdrant.retrieve_authorized_chunks,
            cancellation_token,
            qdrant_filter=qdrant_filter,
            structured_only=False,
            limit=_DOCUMENT_SCOPE_SCAN_LIMIT,
        )
        document_scope_hits = _document_scope_hits(active_query, scope_hits)
        if document_scope_hits:
            scoped_doc_ids = _doc_ids(document_scope_hits)
            ranked = dedupe_hits(
                [
                    *document_scope_hits,
                    *[hit for hit in ranked if _hit_doc_id(hit) in scoped_doc_ids],
                ]
            )
    if (
        _artifact_requires_structured_rows(artifact_plan)
        and ctx["request"].document_ids
        and hasattr(qdrant, "retrieve_document_chunks")
    ):
        scoped_chunks = call_with_optional_cancellation(
            qdrant.retrieve_document_chunks,
            cancellation_token,
            document_ids=ctx["request"].document_ids,
            qdrant_filter=qdrant_filter,
            structured_only=True,
            limit=2000,
        )
        ranked = dedupe_hits(
            [*ranked, *_annotate_structured_hits(scoped_chunks, origin="scope_scan")]
        )
    recall_queries = _recall_expansion_queries(active_query, ranked)
    if recall_queries:
        recall_hits: list[SearchHit] = []
        recall_limit = max(top_k * 2, 12)
        for recall_query in recall_queries:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            dense_vector = call_with_optional_cancellation(
                ollama.embed, cancellation_token, recall_query
            )
            recall_hits.extend(
                _annotate_recall_hits(
                    _search_query(
                        recall_query,
                        dense_vector=dense_vector,
                        limit=recall_limit,
                        qdrant_filter=qdrant_filter,
                        config=config,
                        qdrant=qdrant,
                        cancellation_token=cancellation_token,
                    ),
                    recall_query=recall_query,
                )
            )
        if recall_hits:
            ranked = dedupe_hits([*recall_hits, *ranked])
    return apply_route_retrieval_policy(ranked, plan)
