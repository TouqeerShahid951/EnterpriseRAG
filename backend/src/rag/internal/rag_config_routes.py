"""Internal RAG configuration endpoint for workers."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..query.configuration.repository import RagConfigRepository, effective_rag_config, get_rag_config_repository
from ..query.configuration.mapping import rag_config_response
from rag.query.configuration.schemas import RagConfigResponse
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-rag-config"], dependencies=[Depends(require_service_token)])


@router.get(
    "/rag-config",
    response_model=RagConfigResponse,
    summary="Get effective RAG model runtime config for internal workers",
)
async def get_internal_rag_config(
    repo: RagConfigRepository = Depends(get_rag_config_repository),
) -> RagConfigResponse:
    return rag_config_response(effective_rag_config(repo=repo))
