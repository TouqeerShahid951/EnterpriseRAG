"""Composition providers for document access-scope workflows."""

from __future__ import annotations

from fastapi import Depends

from rag.auth.identity_models import IdentityRepository
from rag.auth.identity_repository import get_identity_repository
from rag.core.config import settings
from rag.graphrag.cleanup import deletion_service_from_settings
from rag.graphrag.maintenance_queue import GraphRAGMaintenanceQueue
from rag.graphrag.maintenance_queue_dependencies import (
    get_graphrag_maintenance_queue,
)
from rag.ingestion.configuration import IngestConfigRepository
from rag.ingestion.configuration.dependencies import (
    effective_ingest_config,
    get_ingest_config_repository,
)
from rag.ingestion.job_dependencies import get_ingest_job_repository
from rag.ingestion.job_models import IngestJobRepository
from rag.query.qdrant import QdrantClient
from rag.documents.access_scope.ports import (
    DocumentAccessScopeIndex,
    DocumentGraphIndexQueue,
    DocumentGraphStore,
)
from rag.documents.access_scope.service import DocumentAccessScopeService
from rag.documents.adapters.access_scope_graph import (
    GraphRAGDocumentIndexQueue,
    GraphRAGDocumentStore,
)
from rag.documents.adapters.access_scope_index import QdrantDocumentAccessScopeIndex
from rag.documents.models import DocumentRepository
from rag.documents.repository import get_document_repository


def get_document_access_scope_index() -> DocumentAccessScopeIndex:
    return QdrantDocumentAccessScopeIndex(
        QdrantClient(
            base_url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            timeout_seconds=settings.rag_http_timeout_seconds,
        )
    )


def get_document_access_scope_graph_store() -> DocumentGraphStore:
    return GraphRAGDocumentStore(deletion_service_from_settings(settings))


def get_document_access_scope_graph_queue(
    queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> DocumentGraphIndexQueue:
    return GraphRAGDocumentIndexQueue(queue)


def get_document_access_scope_service(
    document_repo: DocumentRepository = Depends(get_document_repository),
    identity_repo: IdentityRepository = Depends(get_identity_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    config_repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    index: DocumentAccessScopeIndex = Depends(get_document_access_scope_index),
    graph_store: DocumentGraphStore = Depends(
        get_document_access_scope_graph_store
    ),
    graph_queue: DocumentGraphIndexQueue = Depends(
        get_document_access_scope_graph_queue
    ),
) -> DocumentAccessScopeService:
    def graph_refresh_enabled() -> bool:
        config = effective_ingest_config(repo=config_repo)
        return settings.graphrag_enabled and config.graph_enrichment_enabled

    return DocumentAccessScopeService(
        document_repo=document_repo,
        identity_repo=identity_repo,
        job_repo=job_repo,
        index=index,
        graph_store=graph_store,
        graph_queue=graph_queue,
        graph_refresh_enabled=graph_refresh_enabled,
    )
