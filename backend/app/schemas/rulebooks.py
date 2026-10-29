from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import RulebookStatus


class RulebookRead(BaseModel):
    """A rulebook as returned by the API, with its game's current name."""

    id: int
    game_id: int
    game_name: str
    filename: str
    page_count: int
    status: RulebookStatus
    error: str | None
    created_at: datetime
    updated_at: datetime


class RulebookUpdate(BaseModel):
    """Body for renaming a rulebook or moving it to another game; send only what changes."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    game_id: int | None = None
    filename: Annotated[str, Field(min_length=1, max_length=255)] | None = None

    @model_validator(mode="after")
    def reject_nulls(self) -> Self:
        """Reject null for any field that was sent: both columns are required."""
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self
