from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Result of the API health check."""

    status: Literal["ok", "degraded"] = Field(
        description="`ok` when every dependency is reachable; `degraded` when any is not."
    )
    database: Literal["ok", "unreachable"] = Field(
        description="`ok` when the database answered a test query within 2 seconds; "
        "`unreachable` otherwise."
    )
