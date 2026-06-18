"""Admin ingestion worker capacity routes."""

from fastapi import APIRouter, Depends

from ...auth.dependencies import require_platform_admin_user
from ...repositories.document_models import DocumentRepository
from ...repositories.documents import get_document_repository
from ...repositories.identity import UserRecord
from ...repositories.ingest_config import (
    IngestConfigRecord,
    IngestConfigRepository,
    effective_ingest_config,
    get_ingest_config_repository,
)
from ...schemas.ingest_config import IngestConfigRequest, IngestConfigResponse, IngestWorkerState
from ...services.ingest_worker_control import IngestWorkerControl, WorkerControlResult, get_ingest_worker_control

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ingest-config", response_model=IngestConfigResponse)
def get_ingest_config(
    user: UserRecord = Depends(require_platform_admin_user),
    repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    control: IngestWorkerControl = Depends(get_ingest_worker_control),
) -> IngestConfigResponse:
    _ = user
    config = effective_ingest_config(repo=repo)
    return _response(config, control.snapshot(config.worker_concurrency))


@router.put("/ingest-config", response_model=IngestConfigResponse)
def update_ingest_config(
    payload: IngestConfigRequest,
    user: UserRecord = Depends(require_platform_admin_user),
    repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    control: IngestWorkerControl = Depends(get_ingest_worker_control),
    document_repo: DocumentRepository = Depends(get_document_repository),
) -> IngestConfigResponse:
    saved = repo.save_active(
        IngestConfigRecord(
            worker_concurrency=payload.worker_concurrency,
            ocr_review_confidence_threshold=payload.ocr_review_confidence_threshold,
            updated_by=user.id,
        )
    )
    result = control.apply(saved.worker_concurrency)
    document_repo.append_audit_event(
        event_type="admin.ingest.config",
        actor_id=user.id,
        target_type="workspace_ingest_config",
        target_id=None,
        payload={
            "worker_concurrency": saved.worker_concurrency,
            "ocr_review_confidence_threshold": saved.ocr_review_confidence_threshold,
            "apply_status": result.apply_status,
            "worker_online": result.worker_online,
        },
    )
    return _response(saved, result)


def _response(config: IngestConfigRecord, result: WorkerControlResult) -> IngestConfigResponse:
    return IngestConfigResponse(
        worker_concurrency=config.worker_concurrency,
        ocr_review_confidence_threshold=config.ocr_review_confidence_threshold,
        worker_online=result.worker_online,
        active_jobs=result.active_jobs,
        observed_pool_size=result.observed_pool_size,
        apply_status=result.apply_status,
        workers=[
            IngestWorkerState(name=worker.name, pool_size=worker.pool_size, active_jobs=worker.active_jobs)
            for worker in result.workers
        ],
        hazardous=config.worker_concurrency > 2,
        updated_at=config.updated_at,
    )
