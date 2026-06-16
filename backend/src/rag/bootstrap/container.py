"""Dependency construction helpers for runtime shells."""

from __future__ import annotations

from rag.core.config import Settings
from rag.query.inference import build_inference_client
from rag.query.qdrant import QdrantClient
from rag.repositories.rag_config import env_rag_config
from rag.retrieval import RetrievalService


def build_retrieval_service(config: Settings) -> RetrievalService:
    rag_config = env_rag_config(config)
    embedder = build_inference_client(rag_config, settings=config)
    vector_store = QdrantClient(
        base_url=config.qdrant_url,
        collection=config.qdrant_collection,
        timeout_seconds=config.rag_http_timeout_seconds,
    )
    return RetrievalService(config=config, embedder=embedder, vector_store=vector_store)
