from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    MetaData,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models; holds the shared table metadata."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {datetime: DateTime(timezone=True)}


def _enum_values(enum: type[StrEnum]) -> list[str]:
    return [member.value for member in enum]


def text_enum(enum: type[StrEnum]) -> Enum:
    """Column type that stores a StrEnum as text by value, with a CHECK for its values."""
    return Enum(
        enum,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=_enum_values,
    )


class Game(Base):
    """A board game in the library: a base game or an expansion."""

    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_expansion: Mapped[bool] = mapped_column(server_default=false())
    base_game_id: Mapped[int | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), index=True
    )
    min_players: Mapped[int | None]
    max_players: Mapped[int | None]
    min_age: Mapped[int | None]
    min_play_time_minutes: Mapped[int | None]
    max_play_time_minutes: Mapped[int | None]
    year: Mapped[int | None]
    genres: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    publisher: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "base_game_id IS NULL OR is_expansion", name="base_game_only_for_expansions"
        ),
        CheckConstraint("base_game_id <> id", name="not_own_expansion"),
        CheckConstraint("min_players >= 1", name="min_players_positive"),
        CheckConstraint("max_players >= min_players", name="players_range"),
        CheckConstraint("min_age >= 0", name="min_age_not_negative"),
        CheckConstraint("min_play_time_minutes >= 1", name="min_play_time_positive"),
        CheckConstraint("max_play_time_minutes >= min_play_time_minutes", name="play_time_range"),
    )


class RulebookStatus(StrEnum):
    """Where a rulebook is in the ingestion pipeline."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Rulebook(Base):
    """An uploaded rulebook PDF for a game, and its ingestion state."""

    __tablename__ = "rulebooks"

    id: Mapped[int] = mapped_column(primary_key=True)

    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int]

    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[RulebookStatus] = mapped_column(
        text_enum(RulebookStatus), server_default=RulebookStatus.UPLOADED.value
    )
    error: Mapped[str | None] = mapped_column(Text)
    parse_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
