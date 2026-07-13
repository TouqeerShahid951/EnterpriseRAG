"""Composition helpers for authorized corpus retrieval."""

from __future__ import annotations

from ..core.config import Settings
from ..query.inference import InferenceClient
from ..query.qdrant import QdrantClient
from ..query.rag_config_models import RagConfigRecord
from .adapters.query_runtime import QueryRuntimeAuthorizedCorpusRetriever
from .contracts import AuthorizedCorpusRetriever


def build_authorized_corpus_retriever(
    *,
    config: Settings,
    rag_config: RagConfigRecord,
    inference: InferenceClient,
) -> AuthorizedCorpusRetriever:
    return QueryRuntimeAuthorizedCorpusRetriever(
        config=config,
        rag_config=rag_config,
        inference=inference,
        qdrant=QdrantClient(
            base_url=config.qdrant_url,
            collection=config.qdrant_collection,
            timeout_seconds=config.rag_http_timeout_seconds,
        ),
    )
