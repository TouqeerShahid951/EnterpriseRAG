"""Composition provider for document graph enrichment."""

from fastapi import Depends

from ..core.config import settings
from ..documents.models import DocumentRepository
from ..documents.repository import get_document_repository
from ..ingestion.configuration import IngestConfigRepository
from ..ingestion.configuration_dependencies import (
    effective_ingest_config,
    get_ingest_config_repository,
)
from ..ingestion.job_dependencies import get_ingest_job_repository
from ..ingestion.job_models import IngestJobRepository
from .adapters.document_enrichment_queue import (
    GraphRAGDocumentEnrichmentQueue,
)
from .document_enrichment_service import DocumentGraphEnrichmentService
from .maintenance_queue import GraphRAGMaintenanceQueue
from .maintenance_queue_dependencies import get_graphrag_maintenance_queue


def get_document_graph_enrichment_service(
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    config_repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    queue: GraphRAGMaintenanceQueue = Depends(get_graphrag_maintenance_queue),
) -> DocumentGraphEnrichmentService:
    def enrichment_enabled() -> bool:
        config = effective_ingest_config(repo=config_repo)
        return settings.graphrag_enabled and config.graph_enrichment_enabled

    return DocumentGraphEnrichmentService(
        document_repo=document_repo,
        job_repo=job_repo,
        queue=GraphRAGDocumentEnrichmentQueue(queue),
        enrichment_enabled=enrichment_enabled,
    )
