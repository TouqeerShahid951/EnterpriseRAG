"""Stable retrieval entrypoint used by the query workflow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rag.core.config import Settings
from rag.query.state import QueryContext
from rag.query.retrieval.query_retrieval import retrieve_candidates
from rag.query.cancellation import QueryCancelled
from rag.query.sources.live_sql import retrieve_live_sql_hits
from rag.query.sources import dedupe_hits


class RetrievalService:
    """Coordinate query-time retrieval behind one application-facing API."""

    def __init__(
        self,
        *,
        config: Settings,
        embedder: Any,
        vector_store: Any,
        schedule_repo: Any | None = None,
        connector_profile_repo: Any | None = None,
        connector_registry: Any | None = None,
        reasoning_model: str | None = None,
        sql_generation_model: str | None = None,
    ) -> None:
        self._config = config
        self._embedder = embedder
        self._vector_store = vector_store
        self._schedule_repo = schedule_repo
        self._connector_profile_repo = connector_profile_repo
        self._connector_registry = connector_registry
        self._reasoning_model = reasoning_model
        self._sql_generation_model = sql_generation_model or reasoning_model

    def retrieve(self, ctx: QueryContext) -> list[Any]:
        decision = ctx.get("source_decision")
        mode = str(getattr(decision, "resolved_mode", "") or "")
        if not mode:
            live_hits = self._retrieve_live_sql(ctx)
            vector_hits = self._retrieve_vector(ctx)
            return dedupe_hits([*live_hits, *vector_hits])
        if mode == "corpus_only":
            ctx["execution_modes"]["live_sql_retriever"] = "skipped"
            ctx["execution_details"]["live_sql_retriever"] = "source_mode=corpus_only"
            return self._retrieve_vector(ctx)
        if mode == "db_only":
            live_hits = self._retrieve_live_sql(ctx)
            if not live_hits and bool(getattr(decision, "explicit", False)):
                ctx["degraded"] = True
                ctx["degraded_reason"] = ctx["degraded_reason"] or "explicit_source_no_answer"
                ctx["source_expansion"] = {
                    "available": True,
                    "reason": ctx["execution_details"].get("live_sql_retriever", "selected_source_no_answer"),
                    "suggested_source_mode": "hybrid",
                }
            return live_hits
        if mode == "db_first":
            live_hits = self._retrieve_live_sql(ctx)
            ctx["execution_details"]["source_resolver"] = (
                ctx["execution_details"].get("source_resolver", "") + ",db_first_primary"
            ).strip(",")
            return live_hits
        if mode == "corpus_first":
            vector_hits = self._retrieve_vector(ctx)
            ctx["execution_modes"]["live_sql_retriever"] = "skipped"
            ctx["execution_details"]["live_sql_retriever"] = "source_mode=corpus_first"
            return vector_hits
        if mode == "hybrid":
            preferred = str(getattr(decision, "preferred_source", "") or "")
            expanded_from = ctx.pop("source_expansion_from", None)
            primary_hits = ctx.pop("source_primary_hits", [])
            if expanded_from == "corpus_first":
                live_hits = self._retrieve_live_sql(ctx)
                return dedupe_hits([*primary_hits, *live_hits])
            if expanded_from == "db_first":
                vector_hits = self._retrieve_vector(ctx)
                return dedupe_hits([*primary_hits, *vector_hits])
            return self._retrieve_hybrid(ctx, preferred=preferred)
        return self._retrieve_vector(ctx)

    def _retrieve_live_sql(self, ctx: QueryContext) -> list[Any]:
        try:
            live_sql = retrieve_live_sql_hits(
                ctx,
                config=self._config,
                llm=self._embedder,
                reasoning_model=self._reasoning_model,
                sql_generation_model=self._sql_generation_model,
                schedule_repo=self._schedule_repo,
                connector_profile_repo=self._connector_profile_repo,
                connector_registry=self._connector_registry,
            )
            ctx["execution_modes"]["live_sql_retriever"] = live_sql.mode
            ctx["execution_details"]["live_sql_retriever"] = live_sql.detail
        except QueryCancelled:
            raise
        except Exception as exc:
            ctx["execution_modes"]["live_sql_retriever"] = "fallback"
            ctx["execution_details"]["live_sql_retriever"] = f"discovery_failed:{type(exc).__name__}"
            return []
        return live_sql.hits

    def _retrieve_vector(self, ctx: QueryContext) -> list[Any]:
        return retrieve_candidates(
            ctx,
            config=self._config,
            ollama=self._embedder,
            qdrant=self._vector_store,
        )

    def _retrieve_hybrid(self, ctx: QueryContext, *, preferred: str) -> list[Any]:
        live_ctx = _hybrid_branch_context(ctx)
        vector_ctx = _hybrid_branch_context(ctx)
        # ponytail: request-local workers avoid lifecycle plumbing; use a shared pool only if thread pressure is measured.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-hybrid") as executor:
            live_future = executor.submit(self._retrieve_live_sql, live_ctx)
            vector_future = executor.submit(self._retrieve_vector, vector_ctx)
            live_hits = live_future.result()
            vector_hits = vector_future.result()
        _merge_hybrid_branch_state(ctx, live_ctx=live_ctx, vector_ctx=vector_ctx)
        ctx["execution_details"]["source_resolver"] = (
            ctx["execution_details"].get("source_resolver", "") + ",hybrid_parallel"
        ).strip(",")
        if preferred == "corpus":
            return dedupe_hits([*vector_hits, *live_hits])
        return dedupe_hits([*live_hits, *vector_hits])


def _hybrid_branch_context(ctx: QueryContext) -> QueryContext:
    branch = ctx.copy()
    branch["execution_modes"] = dict(ctx["execution_modes"])
    branch["execution_details"] = dict(ctx["execution_details"])
    branch["retrieval_phase_timings_ms"] = {}
    return branch


def _merge_hybrid_branch_state(
    ctx: QueryContext,
    *,
    live_ctx: QueryContext,
    vector_ctx: QueryContext,
) -> None:
    ctx["execution_modes"].update(vector_ctx["execution_modes"])
    ctx["execution_modes"].update(live_ctx["execution_modes"])
    ctx["execution_details"].update(vector_ctx["execution_details"])
    ctx["execution_details"].update(live_ctx["execution_details"])
    phase_timings = dict(ctx.get("retrieval_phase_timings_ms", {}))
    for branch in (vector_ctx, live_ctx):
        for phase, duration_ms in branch.get(
            "retrieval_phase_timings_ms", {}
        ).items():
            phase_timings[phase] = phase_timings.get(phase, 0) + duration_ms
    if phase_timings:
        ctx["retrieval_phase_timings_ms"] = phase_timings
    ctx["degraded"] = vector_ctx["degraded"] or live_ctx["degraded"]
    ctx["degraded_reason"] = vector_ctx["degraded_reason"] or live_ctx["degraded_reason"]
    if "exhaustive_deadline" in vector_ctx:
        ctx["exhaustive_deadline"] = vector_ctx["exhaustive_deadline"]
    if "exhaustive_coverage" in vector_ctx:
        ctx["exhaustive_coverage"] = vector_ctx["exhaustive_coverage"]
