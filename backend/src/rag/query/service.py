"""Application service for the current local query runtime."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from ..artifact_jobs.service import ArtifactJobService, default_artifact_job_service
from ..auth.context import UserContext
from ..core.config import Settings, settings
from ..repositories.claims import claim_repository_from_settings
from ..repositories.document_memory import InMemoryDocumentRepository
from ..repositories.document_models import DocumentRepository
from ..repositories.document_postgres import PostgresDocumentRepository
from ..repositories.rag_config import RagConfigRepository, effective_rag_config, env_rag_config
from ..schemas.query import QueryRequest, QueryStreamEvent, RAGResponse
from .artifact_service import GeneratedArtifactService
from .artifact_intent import parse_artifact_request
from .cancellation import QueryCancellationToken
from .conflicts import ConflictChecker
from .inference import InferenceClient, build_inference_client
from .qdrant import QdrantClient
from .state import initial_state
from .graph import QueryGraphRunner
from .query_memory import QuerySessionStore, default_query_session_store
from .nodes import QueryNodes
from .query_stream import stream_graph
from .routing_logs import log_query_complete, log_query_error, log_query_start


class LocalRagService:
    def __init__(
        self,
        *,
        config: Settings = settings,
        ollama: InferenceClient | None = None,
        qdrant: QdrantClient | None = None,
        session_store: QuerySessionStore | None = None,
        conflict_checker: ConflictChecker | None = None,
        rag_config_repo: RagConfigRepository | None = None,
        artifact_service: GeneratedArtifactService | None = None,
        artifact_job_service: ArtifactJobService | None = None,
        document_repo: DocumentRepository | None = None,
    ) -> None:
        self.config = config
        self.rag_config = (
            effective_rag_config(config=config, repo=rag_config_repo)
            if ollama is None
            else env_rag_config(config)
        )
        self.ollama = ollama or build_inference_client(self.rag_config, settings=config)
        self.qdrant = qdrant or QdrantClient(
            base_url=config.qdrant_url,
            collection=config.qdrant_collection,
            timeout_seconds=config.rag_http_timeout_seconds,
        )
        self.nodes = QueryNodes(
            config=config,
            ollama=self.ollama,
            qdrant=self.qdrant,
            session_store=session_store or default_query_session_store(),
            conflict_checker=conflict_checker or claim_repository_from_settings(config),
            artifact_service=artifact_service,
            reasoning_model=self.rag_config.effective_reasoning_model or self.rag_config.chat_model,
            routing_model=(
                self.rag_config.routing_model
                or self.rag_config.effective_reasoning_model
                or self.rag_config.chat_model
            ),
            faithfulness_model=self.rag_config.faithfulness_model or self.rag_config.chat_model,
            reranker_model=self.rag_config.reranker_model,
            query_planner_enabled=self.rag_config.query_planner_enabled,
            document_repo=document_repo or _document_repository_from_config(config),
        )
        self.artifact_job_service = artifact_job_service or default_artifact_job_service()
        self.graph = QueryGraphRunner(self.nodes)

    def answer_query(
        self,
        request: QueryRequest,
        user: UserContext,
        *,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> RAGResponse:
        started = perf_counter()
        trace_id = str(uuid4())
        session_id = request.session_id or str(uuid4())
        async_request = self._async_artifact_request(request)
        if async_request is not None:
            return self._enqueue_artifact_job(
                request=request,
                user=user,
                trace_id=trace_id,
                session_id=session_id,
                formats=async_request.formats,
                started=started,
            )
        ctx = initial_state(
            trace_id=trace_id,
            session_id=session_id,
            request=request,
            user=user,
            started=started,
            token_budget=self.rag_config.retrieval_token_budget,
            cancellation_token=cancellation_token,
        )
        log_query_start(ctx, stream=False)
        try:
            result = self.graph.invoke(ctx)
        except Exception as exc:
            log_query_error(ctx, stream=False, exc=exc)
            raise
        log_query_complete(result, stream=False)
        return result["response"]

    def stream_query(
        self,
        request: QueryRequest,
        user: UserContext,
        *,
        cancellation_token: QueryCancellationToken | None = None,
    ):
        started = perf_counter()
        trace_id = str(uuid4())
        session_id = request.session_id or str(uuid4())
        async_request = self._async_artifact_request(request)
        ctx = initial_state(
            trace_id=trace_id,
            session_id=session_id,
            request=request,
            user=user,
            started=started,
            token_budget=self.rag_config.retrieval_token_budget,
            cancellation_token=cancellation_token,
        )
        log_query_start(ctx, stream=True)
        if async_request is not None:
            try:
                response = self._enqueue_artifact_job(
                    request=request,
                    user=user,
                    trace_id=trace_id,
                    session_id=session_id,
                    formats=async_request.formats,
                    started=started,
                )
                ctx["response"] = response
                yield from (
                    QueryStreamEvent(event="trace", data={"trace_id": trace_id, "session_id": session_id}),
                    QueryStreamEvent(event="artifact_job", data=response.artifact_job.model_dump() if response.artifact_job else {}),
                    QueryStreamEvent(event="token", data={"text": response.answer}),
                    QueryStreamEvent(event="done", data=response.model_dump()),
                )
            except Exception as exc:
                log_query_error(ctx, stream=True, exc=exc)
                raise
            log_query_complete(ctx, stream=True)
            return
        try:
            yield from stream_graph(ctx, self.nodes)
        except Exception as exc:
            log_query_error(ctx, stream=True, exc=exc)
            raise
        log_query_complete(ctx, stream=True)

    def _async_artifact_request(self, request: QueryRequest):
        if self.config.artifact_pipeline_version.strip().lower() != "v2":
            return None
        return parse_artifact_request(request.query)

    def _run_graph(
        self,
        *,
        request: QueryRequest,
        user: UserContext,
        trace_id: str,
        session_id: str,
        started: float,
        cancellation_token: QueryCancellationToken | None,
        stream: bool,
    ) -> RAGResponse:
        ctx = initial_state(
            trace_id=trace_id,
            session_id=session_id,
            request=request,
            user=user,
            started=started,
            token_budget=self.rag_config.retrieval_token_budget,
            cancellation_token=cancellation_token,
        )
        log_query_start(ctx, stream=stream)
        try:
            result = self.graph.invoke(ctx)
        except Exception as exc:
            log_query_error(ctx, stream=stream, exc=exc)
            raise
        log_query_complete(result, stream=stream)
        return result["response"]

    def _enqueue_artifact_job(
        self,
        *,
        request: QueryRequest,
        user: UserContext,
        trace_id: str,
        session_id: str,
        formats,
        started: float,
    ) -> RAGResponse:
        turns = self.nodes.session_store.load(user=user, session_id=session_id)
        job = self.artifact_job_service.submit(
            request=request,
            user=user,
            trace_id=trace_id,
            session_id=session_id,
            formats=formats,
            conversation_context=turns,
        )
        return RAGResponse(
            trace_id=trace_id,
            answer=(
                "Document generation is waiting for clarification."
                if job.status == "needs_input"
                else "Document generation has been queued. Progress and downloads will appear here."
            ),
            sources=[],
            artifacts=job.artifacts,
            artifact_job=job,
            conflict_flag=False,
            conflict_detail=None,
            faithfulness_score=1.0,
            faithfulness_status="pending",
            unfounded_claims=[],
            intent="conversational",
            session_id=session_id,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            node_timings=[],
            degraded=False,
            degraded_reason=None,
        )


def _document_repository_from_config(config: Settings) -> DocumentRepository:
    if config.document_repository == "memory":
        return InMemoryDocumentRepository()
    return PostgresDocumentRepository(config.database_url)


def get_local_rag_service() -> LocalRagService:
    return LocalRagService()
