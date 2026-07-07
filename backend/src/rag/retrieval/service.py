"""Stable retrieval entrypoint used by the query workflow."""

from __future__ import annotations

from typing import Any

from rag.core.config import Settings
from rag.query.state import QueryContext
from rag.query.query_retrieval import retrieve_candidates
from rag.query.cancellation import QueryCancelled
from rag.query.live_sql import retrieve_live_sql_hits
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
    ) -> None:
        self._config = config
        self._embedder = embedder
        self._vector_store = vector_store
        self._schedule_repo = schedule_repo
        self._connector_profile_repo = connector_profile_repo
        self._connector_registry = connector_registry
        self._reasoning_model = reasoning_model

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
            if live_hits:
                ctx["execution_details"]["source_resolver"] = (
                    ctx["execution_details"].get("source_resolver", "") + ",db_first_satisfied"
                ).strip(",")
                return live_hits
            return self._retrieve_vector(ctx)
        if mode == "hybrid":
            preferred = str(getattr(decision, "preferred_source", "") or "")
            if preferred == "corpus":
                vector_hits = self._retrieve_vector(ctx)
                live_hits = self._retrieve_live_sql(ctx)
                return dedupe_hits([*vector_hits, *live_hits])
            live_hits = self._retrieve_live_sql(ctx)
            vector_hits = self._retrieve_vector(ctx)
            return dedupe_hits([*live_hits, *vector_hits])
        vector_hits = self._retrieve_vector(ctx)
        if not vector_hits and int(getattr(decision, "structured_score", 0) or 0) > 0:
            live_hits = self._retrieve_live_sql(ctx)
            return dedupe_hits([*live_hits, *vector_hits])
        ctx["execution_modes"]["live_sql_retriever"] = "skipped"
        ctx["execution_details"]["live_sql_retriever"] = "source_mode=corpus_first"
        return vector_hits

    def _retrieve_live_sql(self, ctx: QueryContext) -> list[Any]:
        try:
            live_sql = retrieve_live_sql_hits(
                ctx,
                config=self._config,
                llm=self._embedder,
                reasoning_model=self._reasoning_model,
                schedule_repo=self._schedule_repo,
                connector_profile_repo=self._connector_profile_repo,
                connector_registry=self._connector_registry,
            )
            ctx["execution_modes"]["live_sql_retriever"] = live_sql.mode
            ctx["execution_details"]["live_sql_retriever"] = live_sql.detail
            live_hits = live_sql.hits
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
