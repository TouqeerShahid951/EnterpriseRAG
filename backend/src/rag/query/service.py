"""Application service for the current local query runtime."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from ..artifact_jobs.dependencies import get_artifact_job_service
from ..abbreviations.dependencies import abbreviation_repository_from_settings
from ..abbreviations.models import AbbreviationRepository
from ..abbreviations.service import AbbreviationGlossaryService
from ..artifact_jobs.service import ArtifactJobService
from ..artifact_jobs.submission import ArtifactJobSubmission
from ..artifact_jobs.grounded_response import (
    build_grounded_artifact_payload,
    grounded_response_is_ready,
)
from ..auth.context import UserContext
from ..core.config import Settings, settings
from ..documents.claim_dependencies import claim_repository_from_settings
from ..documents.adapters.memory import InMemoryDocumentRepository
from ..documents.models import DocumentRepository
from ..documents.adapters.postgres import PostgresDocumentRepository
from ..ingestion.publication.dependencies import active_generation_resolver_for
from ..ingestion.configuration import IngestConfigRepository
from ..ingestion.configuration.dependencies import effective_ingest_config
from .schemas import QueryRequest, QueryStreamEvent, RAGResponse
from .artifact_intent import (
    ArtifactRequest,
    parse_artifact_request,
    references_previous_answer,
    requires_conversation_context,
    requires_document_scope,
)
from .cancellation import QueryCancellationToken, QueryCancelled
from rag.query.answering.conflicts import ConflictChecker
from .inference import InferenceClient, build_inference_client
from rag.auth.identity_models import IdentityRepository
from rag.auth.identity_repository import get_identity_repository
from .qdrant import QdrantClient
from .configuration.models import RagConfigRecord, RagConfigRepository
from .configuration.repository import effective_rag_config, env_rag_config
from .state import initial_state
from .graph import QueryGraphRunner
from .chat_history_models import (
    ChatHistoryRepository,
    ChatHistoryRequestConflict,
    context_turn_for_message_id,
)
from .chat_history_repository import default_chat_history_repository
from .nodes import QueryNodes
from .history_access import context_is_available
from .query_stream import stream_graph
from rag.query.retrieval.retrieval_trace import RetrievalTrace
from rag.query.routing.routing_logs import log_query_complete, log_query_error, log_query_start
from rag.query.routing.conversation_resolution import resolve_conversation
from rag.shared.contracts.evidence import SourceAnchor
from .analytics.models import AnalyticsOrigin
from .analytics.repository import analytics_repository_from_config
from .analytics.service import AnalyticsRecorder

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueryExecutionResult:
    response: RAGResponse
    retrieval_trace: RetrievalTrace


class LocalRagService:
    def __init__(
        self,
        *,
        config: Settings = settings,
        ollama: InferenceClient | None = None,
        qdrant: QdrantClient | None = None,
        chat_history_repo: ChatHistoryRepository | None = None,
        conflict_checker: ConflictChecker | None = None,
        rag_config_repo: RagConfigRepository | None = None,
        rag_config: RagConfigRecord | None = None,
        artifact_job_service: ArtifactJobService | None = None,
        document_repo: DocumentRepository | None = None,
        identity_repo: IdentityRepository | None = None,
        abbreviation_repo: AbbreviationRepository | None = None,
        ingest_config_repo: IngestConfigRepository | None = None,
        analytics_recorder: AnalyticsRecorder | None = None,
    ) -> None:
        self.config = config
        self.analytics_recorder = analytics_recorder
        if self.analytics_recorder is None:
            try:
                self.analytics_recorder = AnalyticsRecorder(
                    analytics_repository_from_config(config),
                    reconciliation_grace_seconds=config.query_analytics_reconciliation_grace_seconds,
                    retrieval_lineage_max_candidates=config.query_analytics_retrieval_lineage_max_candidates,
                    retrieval_lineage_max_bytes=config.query_analytics_retrieval_lineage_max_bytes,
                )
            except Exception:  # noqa: BLE001 - an analytics outage must not stop the query
                logger.warning("query analytics initialization failed; capture unavailable")
        resolved_document_repo = document_repo or _document_repository_from_config(config)
        self.rag_config = rag_config or (
            effective_rag_config(config=config, repo=rag_config_repo)
            if ollama is None
            else env_rag_config(config)
        )
        self.analytics_cohort = _analytics_cohort(config, self.rag_config)
        self.ollama = ollama or build_inference_client(self.rag_config, settings=config)
        self.qdrant = qdrant or QdrantClient(
            base_url=config.qdrant_url,
            collection=config.qdrant_collection,
            timeout_seconds=config.rag_http_timeout_seconds,
            active_generation_resolver=active_generation_resolver_for(config),
        )
        self.chat_history_repo = chat_history_repo or default_chat_history_repository()
        self.nodes = QueryNodes(
            config=config,
            ollama=self.ollama,
            qdrant=self.qdrant,
            chat_history_repo=self.chat_history_repo,
            conflict_checker=conflict_checker or claim_repository_from_settings(config),
            reasoning_model=self.rag_config.effective_reasoning_model or self.rag_config.chat_model,
            sql_generation_model=(
                self.rag_config.effective_sql_generation_model
                or self.rag_config.chat_model
            ),
            routing_model=(
                self.rag_config.routing_model
                or self.rag_config.effective_reasoning_model
                or self.rag_config.chat_model
            ),
            faithfulness_model=self.rag_config.faithfulness_model or self.rag_config.chat_model,
            evidence_gate_policy=self.rag_config.evidence_gate_policy,
            faithfulness_policy=self.rag_config.faithfulness_policy,
            reranker_model=self.rag_config.reranker_model,
            context_resolver_enabled=self.rag_config.context_resolver_enabled,
            query_planner_enabled=self.rag_config.query_planner_enabled,
            graph_enabled=(
                config.graphrag_enabled
                and effective_ingest_config(
                    config=config,
                    repo=ingest_config_repo,
                ).graph_enrichment_enabled
            ),
            document_repo=resolved_document_repo,
            identity_repo=identity_repo or get_identity_repository(),
            faithfulness_timeout_seconds=self.rag_config.faithfulness_timeout_seconds,
            citation_output_tokens=self.rag_config.json_num_predict,
            abbreviation_service=AbbreviationGlossaryService(
                abbreviation_repo or abbreviation_repository_from_settings()
            ),
        )
        self.artifact_job_service = artifact_job_service or get_artifact_job_service()
        self.graph = QueryGraphRunner(self.nodes)

    def answer_query(
        self,
        request: QueryRequest,
        user: UserContext,
        *,
        cancellation_token: QueryCancellationToken | None = None,
    ) -> RAGResponse:
        result = self.execute_query(
            request,
            user,
            cancellation_token=cancellation_token,
            capture_retrieval_trace=False,
        )
        self._record_completed_query(request=request, user=user, response=result.response)
        return result.response

    def execute_query(
        self,
        request: QueryRequest,
        user: UserContext,
        *,
        cancellation_token: QueryCancellationToken | None = None,
        capture_retrieval_trace: bool = False,
        force_faithfulness_check: bool = False,
        analytics_origin: AnalyticsOrigin = "chat",
    ) -> QueryExecutionResult:
        started = perf_counter()
        trace_id = str(uuid4())
        session_id = request.session_id or str(uuid4())
        async_request = self._async_artifact_request(request)
        analytics = getattr(self, "analytics_recorder", None)
        ctx = initial_state(
            trace_id=trace_id,
            session_id=session_id,
            request=request,
            user=user,
            started=started,
            token_budget=self.rag_config.retrieval_token_budget,
            cancellation_token=cancellation_token,
            capture_retrieval_trace=capture_retrieval_trace or analytics is not None,
            force_faithfulness_check=force_faithfulness_check,
        )
        if analytics is not None:
            analytics.start(
                execution_id=trace_id,
                trace_id=trace_id,
                session_id=session_id,
                user=user,
                request=request,
                started_at=datetime.now(UTC),
                origin=analytics_origin,
                work_kind="artifact_submission" if async_request is not None else "answer",
                cohort=self.analytics_cohort,
            )
        with analytics.heartbeat(trace_id) if analytics is not None else nullcontext():
            log_query_start(ctx, stream=False)
            try:
                if async_request is not None:
                    response = self._handle_artifact_request(
                        request=request,
                        artifact_request=async_request,
                        user=user,
                        trace_id=trace_id,
                        session_id=session_id,
                        started=started,
                        cancellation_token=cancellation_token,
                    )
                    ctx["response"] = response
                else:
                    result = self.graph.invoke(ctx)
                    response = result["response"]
                    ctx = result
            except QueryCancelled as exc:
                if analytics is not None:
                    analytics.fail(execution_id=trace_id, outcome="cancelled", ctx=ctx)
                log_query_error(ctx, stream=False, exc=exc)
                raise
            except Exception as exc:
                if analytics is not None:
                    analytics.fail(execution_id=trace_id, ctx=ctx)
                log_query_error(ctx, stream=False, exc=exc)
                raise
            log_query_complete(ctx, stream=False)
            if analytics is not None:
                analytics.finish_response(
                    execution_id=trace_id,
                    response=response,
                    ctx=ctx,
                )
            return QueryExecutionResult(
                response=response,
                retrieval_trace=RetrievalTrace(tuple(ctx.get("retrieval_trace", ()))),
            )

    def stream_query(
        self,
        request: QueryRequest,
        user: UserContext,
        *,
        cancellation_token: QueryCancellationToken | None = None,
        capture_retrieval_trace: bool = False,
        analytics_origin: AnalyticsOrigin = "chat",
    ):
        started = perf_counter()
        trace_id = str(uuid4())
        session_id = request.session_id or str(uuid4())
        async_request = self._async_artifact_request(request)
        analytics = getattr(self, "analytics_recorder", None)
        ctx = initial_state(
            trace_id=trace_id,
            session_id=session_id,
            request=request,
            user=user,
            started=started,
            token_budget=self.rag_config.retrieval_token_budget,
            cancellation_token=cancellation_token,
            capture_retrieval_trace=capture_retrieval_trace or analytics is not None,
        )
        if analytics is not None:
            analytics.start(
                execution_id=trace_id,
                trace_id=trace_id,
                session_id=session_id,
                user=user,
                request=request,
                started_at=datetime.now(UTC),
                origin=analytics_origin,
                work_kind="artifact_submission" if async_request is not None else "answer",
                cohort=self.analytics_cohort,
            )
        with analytics.heartbeat(trace_id) if analytics is not None else nullcontext():
            log_query_start(ctx, stream=True)
            if async_request is not None:
                try:
                    response = self._handle_artifact_request(
                        request=request,
                        artifact_request=async_request,
                        user=user,
                        trace_id=trace_id,
                        session_id=session_id,
                        started=started,
                        cancellation_token=cancellation_token,
                    )
                    ctx["response"] = response
                    if analytics is not None:
                        analytics.finish_response(
                            execution_id=trace_id,
                            response=response,
                            ctx=ctx,
                        )
                    self._record_completed_query(
                        request=request,
                        user=user,
                        response=response,
                    )
                    yield QueryStreamEvent(
                        event="trace", data={"trace_id": trace_id, "session_id": session_id}
                    )
                    if response.artifact_job is not None:
                        yield QueryStreamEvent(
                            event="artifact_job",
                            data=response.artifact_job.model_dump(),
                        )
                    yield QueryStreamEvent(event="token", data={"text": response.answer})
                    yield QueryStreamEvent(event="done", data=response.model_dump())
                except QueryCancelled:
                    if analytics is not None:
                        analytics.fail(execution_id=trace_id, outcome="cancelled", ctx=ctx)
                    raise
                except GeneratorExit:
                    if analytics is not None:
                        analytics.fail(execution_id=trace_id, outcome="interrupted", ctx=ctx)
                    raise
                except Exception as exc:
                    if analytics is not None:
                        analytics.fail(execution_id=trace_id, ctx=ctx)
                    log_query_error(ctx, stream=True, exc=exc)
                    raise
                log_query_complete(ctx, stream=True)
                return
            try:
                for event in stream_graph(ctx, self.nodes):
                    if event.event == "done":
                        response = RAGResponse.model_validate(event.data)
                        if analytics is not None:
                            analytics.finish_response(
                                execution_id=trace_id,
                                response=response,
                                ctx=ctx,
                            )
                        self._record_completed_query(
                            request=request,
                            user=user,
                            response=response,
                        )
                    elif event.event == "verified":
                        response = RAGResponse.model_validate(event.data)
                        self.chat_history_repo.update_assistant_response(
                            user_id=user.user_id,
                            permission_version=user.permission_version,
                            session_id=response.session_id,
                            trace_id=response.trace_id,
                            response=response.model_dump(mode="json"),
                        )
                    yield event
            except QueryCancelled:
                if analytics is not None:
                    analytics.fail(execution_id=trace_id, outcome="cancelled", ctx=ctx)
                raise
            except GeneratorExit:
                if analytics is not None:
                    analytics.fail(execution_id=trace_id, outcome="interrupted", ctx=ctx)
                raise
            except Exception as exc:
                if analytics is not None:
                    analytics.fail(execution_id=trace_id, ctx=ctx)
                log_query_error(ctx, stream=True, exc=exc)
                raise
            log_query_complete(ctx, stream=True)

    def _async_artifact_request(self, request: QueryRequest):
        return parse_artifact_request(request.query)

    def _record_completed_query(
        self,
        *,
        request: QueryRequest,
        user: UserContext,
        response: RAGResponse,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        question = request.query.strip()
        client_request_id = request.client_request_id or response.trace_id
        self.chat_history_repo.append_completed_turn(
            user_id=user.user_id,
            permission_version=user.permission_version,
            session_id=response.session_id,
            title=_compact_session_title(question),
            user_turn={
                "id": f"user-{client_request_id}",
                "role": "user",
                "content": question,
                "createdAt": created_at,
                "replyToTurnId": request.reply_to_turn_id,
            },
            assistant_turn={
                "id": client_request_id,
                "role": "assistant",
                "status": "complete",
                "question": question,
                "createdAt": created_at,
                "clientRequestId": client_request_id,
                "replyToTurnId": request.reply_to_turn_id,
                "groupPath": request.group_path,
                "documentIds": request.document_ids,
                "sourceMode": request.source_mode,
                "querySourceId": request.query_source_id,
                "querySourceIds": list(request.effective_query_source_ids),
                "progress": [],
                "response": response.model_dump(mode="json"),
            },
            client_request_id=client_request_id,
            request_fingerprint=_request_fingerprint(request),
            continue_source_clarification=request.continue_source_clarification,
        )


    def _handle_artifact_request(
        self,
        *,
        request: QueryRequest,
        artifact_request: ArtifactRequest,
        user: UserContext,
        trace_id: str,
        session_id: str,
        started: float,
        cancellation_token: QueryCancellationToken | None,
    ) -> RAGResponse:
        if request.effective_query_source_ids or request.source_mode in {"db_only", "hybrid"}:
            return self._artifact_clarification(
                trace_id=trace_id,
                session_id=session_id,
                started=started,
                message=(
                    "Generated files currently use the document corpus. Select corpus "
                    "documents or switch to corpus-only mode before requesting a file."
                ),
            )

        group_path = request.group_path
        document_ids = tuple(request.document_ids)
        resolution_context: list[dict[str, object]] = []
        seeded_payload: dict[str, object] = {}
        if artifact_request.needs_clarification:
            content_query = artifact_request.content_query
            if requires_document_scope(content_query) and document_ids:
                pass
            elif requires_conversation_context(content_query):
                reply_context_turn_id: str | None = None
                if request.reply_to_turn_id:
                    session = self.chat_history_repo.get_session(
                        user_id=user.user_id,
                        permission_version=user.permission_version,
                        session_id=session_id,
                    )
                    reply_turn = (
                        context_turn_for_message_id(
                            session.turns,
                            request.reply_to_turn_id,
                        )
                        if session is not None
                        else None
                    )
                    if reply_turn is None:
                        raise ChatHistoryRequestConflict(
                            "reply target was not found in this chat"
                        )
                    reply_context_turn_id = str(reply_turn.get("turn_id") or "")
                    if not reply_context_turn_id:
                        raise ChatHistoryRequestConflict(
                            "reply target does not identify a complete exchange"
                        )
                    turns = [reply_turn]
                elif self.rag_config.context_resolver_enabled:
                    turns = self.chat_history_repo.load_recent_context_turns(
                        user_id=user.user_id,
                        permission_version=user.permission_version,
                        session_id=session_id,
                        limit=8,
                    )
                else:
                    return self._artifact_clarification(
                        trace_id=trace_id,
                        session_id=session_id,
                        started=started,
                        message="Use Reply on an earlier response to choose what this file should cover.",
                    )
                turns = [turn for turn in turns if context_is_available(
                    turn, user=user, documents=self.nodes.document_repo)]
                if not turns:
                    return self._artifact_clarification(
                        trace_id=trace_id,
                        session_id=session_id,
                        started=started,
                        message="What topic or earlier answer should this file use?",
                    )
                referenced_turns: list[dict[str, object]]
                if references_previous_answer(content_query):
                    referenced_turns = [turns[-1]]
                    previous_query = str(turns[-1].get("query") or "").strip()
                    if not previous_query:
                        return self._artifact_clarification(
                            trace_id=trace_id,
                            session_id=session_id,
                            started=started,
                            message="Which earlier answer should this file use?",
                        )
                    resolution_context = [
                        {
                            "resolved_query": previous_query,
                            "antecedent_turn_ids": [
                                str(turns[-1].get("turn_id") or "")
                            ],
                        }
                    ]
                    seed = self._grounded_artifact_seed(
                        request=request,
                        turn=turns[-1],
                        content_query=previous_query,
                    )
                    if seed is not None:
                        seeded_payload, document_ids, group_path = seed
                        resolution_context = []
                else:
                    resolution = resolve_conversation(
                        request.query,
                        turns,
                        client=self.ollama,
                        model=self.nodes.routing_model,
                        enabled=self.rag_config.context_resolver_enabled,
                        reply_to_turn_id=reply_context_turn_id,
                        has_explicit_scope=bool(
                            document_ids or request.effective_query_source_ids
                        ),
                        cancellation_token=cancellation_token,
                    )
                    if resolution.relation != "follow_up":
                        return self._artifact_clarification(
                            trace_id=trace_id,
                            session_id=session_id,
                            started=started,
                            message=resolution.clarification_question
                            or "Which earlier question or answer should this file use?",
                        )
                    resolution_context = [
                        {
                            "resolved_query": resolution.effective_query,
                            "antecedent_turn_ids": list(
                                resolution.antecedent_turn_ids
                            ),
                        }
                    ]
                    antecedents = set(resolution.antecedent_turn_ids)
                    referenced_turns = [
                        turn
                        for turn in turns
                        if str(turn.get("turn_id") or "") in antecedents
                    ]

                if any(
                    turn.get("query_source_id")
                    or turn.get("source_mode") in {"db_only", "hybrid"}
                    for turn in referenced_turns
                ):
                    return self._artifact_clarification(
                        trace_id=trace_id,
                        session_id=session_id,
                        started=started,
                        message=(
                            "That earlier answer used a database source, which generated "
                            "files do not support yet. Select corpus documents and try again."
                        ),
                    )
                if not document_ids:
                    document_ids = tuple(
                        dict.fromkeys(
                            str(document_id)
                            for turn in referenced_turns
                            for document_id in (turn.get("document_ids") or [])
                            if str(document_id).strip()
                        )
                    )[:20]
                if group_path is None:
                    inherited_paths = {
                        str(turn.get("group_path"))
                        for turn in referenced_turns
                        if turn.get("group_path")
                    }
                    if len(inherited_paths) == 1:
                        group_path = inherited_paths.pop()
            else:
                return self._artifact_clarification(
                    trace_id=trace_id,
                    session_id=session_id,
                    started=started,
                    message="What topic or selected documents should this file cover?",
                )

        job = self.artifact_job_service.submit(
            submission=ArtifactJobSubmission(
                original_request=request.query,
                client_request_id=request.client_request_id,
                group_path=group_path,
                document_ids=document_ids,
            ),
            user=user,
            trace_id=trace_id,
            session_id=session_id,
            formats=artifact_request.formats,
            conversation_context=resolution_context,
            **seeded_payload,
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
            faithfulness_score=0.0,
            faithfulness_status="skipped",
            unfounded_claims=[],
            intent="conversational",
            session_id=session_id,
            latency_ms=max(0, int((perf_counter() - started) * 1000)),
            node_timings=[],
            degraded=False,
            degraded_reason=None,
        )

    def _grounded_artifact_seed(
        self,
        *,
        request: QueryRequest,
        turn: dict[str, object],
        content_query: str,
    ) -> tuple[dict[str, object], tuple[str, ...], str | None] | None:
        answer = str(turn.get("answer") or "").strip()
        raw_sources = turn.get("sources")
        try:
            sources = (
                [SourceAnchor.model_validate(source) for source in raw_sources]
                if isinstance(raw_sources, list)
                else []
            )
        except ValueError:
            return None
        source_doc_ids = tuple(dict.fromkeys(source.doc_id for source in sources))
        if (
            not answer
            or len(source_doc_ids) > 20
            or not grounded_response_is_ready(
                sources=sources,
                degraded=bool(turn.get("degraded")),
                faithfulness_status=turn.get("faithfulness_status"),
            )
        ):
            return None
        plan, evidence, bundle = build_grounded_artifact_payload(
            original_request=request.query,
            content_query=content_query,
            answer=answer,
            sources=sources,
        )
        source_group_paths = {
            source.group_path for source in sources if source.group_path
        }
        group_path = (
            source_group_paths.pop() if len(source_group_paths) == 1 else None
        )
        return (
            {
                "seeded_plan": plan,
                "seeded_evidence": evidence,
                "seeded_bundle": bundle,
            },
            source_doc_ids,
            group_path,
        )

    @staticmethod
    def _artifact_clarification(
        *,
        trace_id: str,
        session_id: str,
        started: float,
        message: str,
    ) -> RAGResponse:
        return RAGResponse(
            trace_id=trace_id,
            answer=message,
            answer_status="clarification",
            sources=[],
            conflict_flag=False,
            conflict_detail=None,
            faithfulness_score=0.0,
            faithfulness_status="skipped",
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


def _request_fingerprint(request: QueryRequest) -> str:
    payload = {
        "query": request.query.strip(),
        "group_path": request.group_path,
        "document_ids": sorted(request.document_ids),
        "source_mode": request.source_mode,
        "query_source_ids": sorted(request.effective_query_source_ids),
        "allow_source_expansion": request.allow_source_expansion,
        "reply_to_turn_id": request.reply_to_turn_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _analytics_cohort(config: Settings, rag_config: RagConfigRecord) -> dict[str, object]:
    models = {
        "chat": rag_config.chat_model,
        "reasoning": rag_config.effective_reasoning_model or rag_config.chat_model,
        "sql_generation": rag_config.effective_sql_generation_model or rag_config.chat_model,
        "routing": rag_config.routing_model or rag_config.chat_model,
        "faithfulness": rag_config.faithfulness_model or rag_config.chat_model,
        "embedding": rag_config.embed_model,
        "reranker": rag_config.reranker_model,
    }
    providers = {
        "reasoning": rag_config.effective_reasoning_provider,
        "routing": rag_config.effective_routing_provider,
        "faithfulness": rag_config.effective_faithfulness_provider,
        "embedding": rag_config.embedding_provider,
    }
    snapshot = {
        "schema_version": 1,
        "models": models,
        "providers": providers,
        "policies": {
            "evidence_gate": rag_config.evidence_gate_policy,
            "faithfulness": rag_config.faithfulness_policy,
        },
        "flags": {
            "thinking_enabled": rag_config.thinking_enabled,
            "context_resolver_enabled": rag_config.context_resolver_enabled,
            "query_planner_enabled": rag_config.query_planner_enabled,
        },
        "limits": {
            "json_num_predict": rag_config.json_num_predict,
            "retrieval_token_budget": rag_config.retrieval_token_budget,
            "answer_output_tokens": rag_config.answer_output_tokens,
            "answer_context_tokens": rag_config.answer_context_tokens,
        },
        "retrieval": {
            "top_k": config.rag_top_k,
            "reranker_max_candidates": config.rag_reranker_max_candidates,
        },
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    model_encoded = json.dumps({"models": models, "providers": providers}, sort_keys=True, separators=(",", ":"))
    return {
        "model_cohort": f"models-{hashlib.sha256(model_encoded.encode('utf-8')).hexdigest()[:16]}",
        "configuration_digest": f"config-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}",
        "application_image_digest": config.application_image_digest,
        "snapshot": snapshot,
    }


def _compact_session_title(value: str) -> str:
    return f"{value[:49].rstrip()}..." if len(value) > 52 else value
