"""Internal ingestion runtime configuration endpoint for workers."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..repositories.ingest_config import IngestConfigRepository, effective_ingest_config, get_ingest_config_repository
from ..schemas.ingest_config import IngestRuntimeConfigResponse
from ..schemas.internal import ServiceTokenContext
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-ingest-config"])


@router.get(
    "/ingest-config",
    response_model=IngestRuntimeConfigResponse,
    summary="Get effective ingestion runtime config for internal workers",
)
async def get_internal_ingest_config(
    repo: IngestConfigRepository = Depends(get_ingest_config_repository),
    service: ServiceTokenContext = Depends(require_service_token),
) -> IngestRuntimeConfigResponse:
    _ = service
    config = effective_ingest_config(repo=repo)
    return IngestRuntimeConfigResponse(
        worker_concurrency=config.worker_concurrency,
        ocr_review_confidence_threshold=config.ocr_review_confidence_threshold,
        source=config.source,
    )
