"""Composition provider for stored-source document reingestion."""

from fastapi import Depends

from ..ingestion.job_dependencies import get_ingest_job_repository
from ..ingestion.job_models import IngestJobRepository
from ..ingestion.queue import IngestQueue, get_ingest_queue
from .dependencies import get_upload_storage
from .models import DocumentRepository
from .reingestion_service import DocumentReingestionService
from .repository import get_document_repository
from .storage import UploadStorage


def get_document_reingestion_service(
    document_repo: DocumentRepository = Depends(get_document_repository),
    job_repo: IngestJobRepository = Depends(get_ingest_job_repository),
    storage: UploadStorage = Depends(get_upload_storage),
    queue: IngestQueue = Depends(get_ingest_queue),
) -> DocumentReingestionService:
    return DocumentReingestionService(
        document_repo=document_repo,
        job_repo=job_repo,
        storage=storage,
        queue=queue,
    )
