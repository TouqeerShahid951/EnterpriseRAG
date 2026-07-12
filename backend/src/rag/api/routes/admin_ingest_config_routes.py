"""Admin ingestion worker capacity routes."""

from fastapi import APIRouter, Depends

from ...auth.dependencies import require_platform_admin_user
from ...repositories.document_models import DocumentRepository
from ...repositories.documents import get_document_repository
from ...auth.identity_models import UserRecord
from ...ingestion.configuration import IngestConfigRecord, IngestConfigRepository
from ...ingestion.configuration_dependencies import (
    effective_ingest_config,
    get_ingest_config_repository,
)
from ...schemas.ingest_config import IngestConfigRequest, IngestConfigResponse, IngestWorkerState
from ...ingestion.worker_control import IngestWorkerControl, WorkerControlResult, get_ingest_worker_control

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
            quality_preset=payload.quality_preset,
            ocr_review_confidence_threshold=payload.ocr_review_confidence_threshold,
            pdf_image_review_threshold=payload.pdf_image_review_threshold,
            vision_layout_repair_enabled=payload.vision_layout_repair_enabled,
            graph_enrichment_enabled=payload.graph_enrichment_enabled,
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
            "quality_preset": saved.quality_preset,
            "ocr_review_confidence_threshold": saved.ocr_review_confidence_threshold,
            "pdf_image_review_threshold": saved.pdf_image_review_threshold,
            "vision_layout_repair_enabled": saved.vision_layout_repair_enabled,
            "graph_enrichment_enabled": saved.graph_enrichment_enabled,
            "apply_status": result.apply_status,
            "worker_online": result.worker_online,
        },
    )
    return _response(saved, result)


def _response(config: IngestConfigRecord, result: WorkerControlResult) -> IngestConfigResponse:
    return IngestConfigResponse(
        worker_concurrency=config.worker_concurrency,
        quality_preset=config.quality_preset,
        ocr_review_confidence_threshold=config.ocr_review_confidence_threshold,
        pdf_image_review_threshold=config.pdf_image_review_threshold,
        vision_layout_repair_enabled=config.vision_layout_repair_enabled,
        graph_enrichment_enabled=config.graph_enrichment_enabled,
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
