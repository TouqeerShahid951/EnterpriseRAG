"""Query-node composition root."""

from __future__ import annotations

from ...core.config import Settings
from rag.shared.contracts.rag_defaults import EvidenceGatePolicy, FaithfulnessPolicy
from rag.abbreviations.service import AbbreviationGlossaryService
from ...retrieval.service import RetrievalService
from rag.query.answering.conflicts import ConflictChecker
from ..inference import InferenceClient
from ..qdrant import QdrantClient
from ..chat_history_models import ChatHistoryRepository
from .response_nodes import ResponseNodes
from .retrieval_nodes import RetrievalNodes
from .routing_nodes import RoutingNodes


class QueryNodes(RoutingNodes, RetrievalNodes, ResponseNodes):
    def __init__(
        self,
        *,
        config: Settings,
        ollama: InferenceClient,
        qdrant: QdrantClient,
        chat_history_repo: ChatHistoryRepository,
        conflict_checker: ConflictChecker,
        reasoning_model: str | None = None,
        sql_generation_model: str | None = None,
        routing_model: str | None = None,
        faithfulness_model: str | None = None,
        evidence_gate_policy: EvidenceGatePolicy | None = None,
        faithfulness_policy: FaithfulnessPolicy | None = None,
        reranker_model: str | None = None,
        query_planner_enabled: bool | None = None,
        schedule_repo: object | None = None,
        connector_profile_repo: object | None = None,
        connector_registry: object | None = None,
        document_repo: object | None = None,
        abbreviation_service: AbbreviationGlossaryService | None = None,
    ) -> None:
        self.config = config
        self.ollama = ollama
        self.qdrant = qdrant
        self.chat_history_repo = chat_history_repo
        self.conflict_checker = conflict_checker
        self.reasoning_model = (
            reasoning_model
            or routing_model
            or config.rag_routing_model
            or config.ollama_chat_model
        )
        self.routing_model = routing_model or self.reasoning_model
        self.sql_generation_model = sql_generation_model or self.reasoning_model
        self.faithfulness_model = faithfulness_model or config.rag_faithfulness_model or config.ollama_chat_model
        self.evidence_gate_policy = evidence_gate_policy or config.rag_evidence_gate_policy
        self.faithfulness_policy = faithfulness_policy or config.rag_faithfulness_policy
        self.reranker_model = reranker_model or config.rag_reranker_model
        self.query_planner_enabled = config.rag_query_planner_enabled if query_planner_enabled is None else query_planner_enabled
        self.schedule_repo = schedule_repo
        self.connector_profile_repo = connector_profile_repo
        self.document_repo = document_repo
        self.abbreviation_service = abbreviation_service
        self.retrieval_service = RetrievalService(
            config=config,
            embedder=ollama,
            vector_store=qdrant,
            schedule_repo=schedule_repo,
            connector_profile_repo=connector_profile_repo,
            connector_registry=connector_registry,
            reasoning_model=self.reasoning_model,
            sql_generation_model=self.sql_generation_model,
        )
