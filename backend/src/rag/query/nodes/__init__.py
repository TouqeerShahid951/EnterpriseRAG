"""LangGraph query-node composition root."""

from __future__ import annotations

from ...core.config import Settings
from ...retrieval.service import RetrievalService
from ..artifact_service import GeneratedArtifactService, generated_artifact_service_from_settings
from rag.query.answering.conflicts import ConflictChecker
from ..inference import InferenceClient
from ..qdrant import QdrantClient
from ..query_memory import QuerySessionStore
from .artifact_nodes import ArtifactNodes
from .response_nodes import ResponseNodes
from .retrieval_nodes import RetrievalNodes
from .routing_nodes import RoutingNodes


class QueryNodes(RoutingNodes, RetrievalNodes, ArtifactNodes, ResponseNodes):
    def __init__(
        self,
        *,
        config: Settings,
        ollama: InferenceClient,
        qdrant: QdrantClient,
        session_store: QuerySessionStore,
        conflict_checker: ConflictChecker,
        artifact_service: GeneratedArtifactService | None = None,
        reasoning_model: str | None = None,
        routing_model: str | None = None,
        faithfulness_model: str | None = None,
        reranker_model: str | None = None,
        query_planner_enabled: bool | None = None,
        schedule_repo: object | None = None,
        connector_profile_repo: object | None = None,
        connector_registry: object | None = None,
        document_repo: object | None = None,
    ) -> None:
        self.config = config
        self.ollama = ollama
        self.qdrant = qdrant
        self.session_store = session_store
        self.conflict_checker = conflict_checker
        self.artifact_service = artifact_service or generated_artifact_service_from_settings(config)
        self.reasoning_model = reasoning_model or routing_model or config.rag_route_llm_verifier_model or config.ollama_chat_model
        self.routing_model = routing_model or self.reasoning_model
        self.faithfulness_model = faithfulness_model or config.rag_faithfulness_model or config.ollama_chat_model
        self.reranker_model = reranker_model or config.rag_reranker_model
        self.query_planner_enabled = config.rag_query_planner_enabled if query_planner_enabled is None else query_planner_enabled
        self.schedule_repo = schedule_repo
        self.connector_profile_repo = connector_profile_repo
        self.document_repo = document_repo
        self.retrieval_service = RetrievalService(
            config=config,
            embedder=ollama,
            vector_store=qdrant,
            schedule_repo=schedule_repo,
            connector_profile_repo=connector_profile_repo,
            connector_registry=connector_registry,
            reasoning_model=self.reasoning_model,
        )
