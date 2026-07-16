from fastapi import APIRouter, Depends, Query

from ..auth.abac import build_abac_filter
from ..auth.context import UserContext
from rag.auth.schemas.internal import AbacFilterResponse
from rag.internal.schemas import ServiceTokenContext
from .service_token_auth import require_service_token

router = APIRouter(tags=["internal-abac"])


@router.get(
    "/abac-filter",
    response_model=AbacFilterResponse,
    summary="Build the canonical Qdrant ABAC filter",
)
async def get_abac_filter(
    user_id: str,
    email: str = "service-user@prudentia.ai",
    group_paths: list[str] = Query(default_factory=list),
    clearance_level: str = "NATO_RESTRICTED",
    permission_version: int = 0,
    is_current_only: bool = True,
    service: ServiceTokenContext = Depends(require_service_token),
) -> AbacFilterResponse:
    user = UserContext(
        user_id=user_id,
        email=email,
        group_paths=tuple(group_paths),
        clearance_level=clearance_level,
        permission_version=permission_version,
    )
    return AbacFilterResponse(filter=build_abac_filter(user, is_current_only=is_current_only))
