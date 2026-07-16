from fastapi import Header, HTTPException, status

from ..core.config import settings
from rag.internal.schemas import ServiceTokenContext


async def require_service_token(
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
) -> ServiceTokenContext:
    if not x_service_token or x_service_token != settings.service_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "service_token_required", "message": "Valid service token required."},
        )

    return ServiceTokenContext(service_name="scaffold", scopes=("m0:stub",))
