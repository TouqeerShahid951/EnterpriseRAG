"""Composition providers for document lifecycle workflows."""

from __future__ import annotations

from fastapi import Depends

from ..core.config import settings
from ..graphrag.cleanup import deletion_service_from_settings
from ..graphrag.maintenance_queue import GraphRAGMaintenanceQueue
from ..graphrag.maintenance_queue_dependencies import (
    get_graphrag_maintenance_queue,
)
from ..ingestion.job_dependencies import get_ingest_job_repository
from ..ingestion.job_models import IngestJobRepository
from ..ingestion.queue import IngestQueue, get_ingest_queue
from ..query.qdrant import QdrantClient
from ..services.document_image_asset_storage import (
    get_document_image_asset_storage,
)
from .adapters.access_scope_graph import GraphRAGDocumentStore
from .adapters.lifecycle import (
    GraphRAGPartitionRebuildQueue,
    QdrantDocumentVectorIndex,
)
from .dependencies import get_upload_storage
from .lifecycle_ports import (
    DocumentGraphCleanup,
    DocumentImageDeletionStore,
    DocumentVectorIndex,
    GraphPartitionRebuildQueue,
)
from .lifecycle_service import DocumentLifecycleService
from .models import DocumentRepository
from .repository import get_document_repository
from .storage import UploadStorage


def get_document_lifecycle_vector_index() -> DocumentVectorIndex:
    return QdrantDocumentVectorIndex(
        QdrantClient(
            base_url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            timeout_seconds=settings.rag_http_timeout_seconds,
        )
    )


def get_document_lifecycle_graph_cleanup() -> DocumentGraphCleanup:
    return GraphRAGDocumentStore(deletion_service_from_settings(settings))


def get_document_lifecycle_graph_queue(
    queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> GraphPartitionRebuildQueue:
    return GraphRAGPartitionRebuildQueue(queue)


def get_document_lifecycle_service(
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    image_storage: DocumentImageDeletionStore = Depends(
        get_document_image_asset_storage
    ),
    ingest_queue: IngestQueue = Depends(get_ingest_queue),
    vectors: DocumentVectorIndex = Depends(get_document_lifecycle_vector_index),
    graph_cleanup: DocumentGraphCleanup = Depends(
        get_document_lifecycle_graph_cleanup
    ),
    graph_queue: GraphPartitionRebuildQueue = Depends(
        get_document_lifecycle_graph_queue
    ),
) -> DocumentLifecycleService:
    return DocumentLifecycleService(
        documents=document_repo,
        jobs=job_repo,
        storage=storage,
        image_storage=image_storage,
        ingest_queue=ingest_queue,
        vectors=vectors,
        graph_cleanup=graph_cleanup,
        graph_queue=graph_queue,
        graphrag_enabled=settings.graphrag_enabled,
        qdrant_collection=settings.qdrant_collection,
    )
