from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_database_reachable
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", responses={503: {"model": HealthResponse}})
async def get_health(
    database_ok: Annotated[bool, Depends(get_database_reachable)], response: Response
) -> HealthResponse:
    """Report whether the API and its database are working; responds 503 when degraded."""
    if database_ok:
        return HealthResponse(status="ok", database="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="degraded", database="unreachable")
