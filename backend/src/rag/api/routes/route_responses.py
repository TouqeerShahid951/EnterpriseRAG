from fastapi import status
from fastapi.responses import JSONResponse

from ...schemas.common import StubResponse


def not_implemented(detail: str = "Route contract is reserved for Milestone 0.") -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=StubResponse(detail=detail).model_dump(),
    )
