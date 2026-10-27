from datetime import datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _normalize_genres(genres: list[str]) -> list[str]:
    cleaned = [genre.strip().lower() for genre in genres]
    return list(dict.fromkeys(genre for genre in cleaned if genre))


# Field rules shared by the create and update schemas, so they can't drift apart.
GameName = Annotated[str, Field(min_length=1, max_length=200)]
IsExpansion = Annotated[
    bool, Field(description="Whether this game is an expansion of another game.")
]
BaseGameId = Annotated[
    int,
    Field(
        description="The base game this expansion belongs to; only for expansions, "
        "and null while the base game isn't in the library."
    ),
]
Count = Annotated[int, Field(ge=1)]  # players and play-time minutes
Age = Annotated[int, Field(ge=0)]
Year = Annotated[int, Field(description="Year of first publication.")]
Genres = Annotated[
    list[str],
    AfterValidator(_normalize_genres),
    Field(description="Genres, stored trimmed, lowercased and without duplicates."),
]


class GameCreate(BaseModel):
    """Body for creating a game."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: GameName
    description: str | None = None
    is_expansion: IsExpansion = False
    base_game_id: BaseGameId | None = None
    min_players: Count | None = None
    max_players: Count | None = None
    min_age: Age | None = None
    min_play_time_minutes: Count | None = None
    max_play_time_minutes: Count | None = None
    year: Year | None = None
    genres: Genres = []
    publisher: str | None = None

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        """Reject ranges that end before they start, and base games with a base game."""
        if (
            self.min_players is not None
            and self.max_players is not None
            and self.max_players < self.min_players
        ):
            raise ValueError("max_players must be at least min_players")

        if (
            self.min_play_time_minutes is not None
            and self.max_play_time_minutes is not None
            and self.max_play_time_minutes < self.min_play_time_minutes
        ):
            raise ValueError("max_play_time_minutes must be at least min_play_time_minutes")

        if self.base_game_id is not None and not self.is_expansion:
            raise ValueError("base_game_id is only allowed for expansions")

        return self


class GameUpdate(BaseModel):
    """Body for changing some fields of a game; send only what changes."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: GameName | None = None
    description: str | None = None
    is_expansion: IsExpansion | None = None
    base_game_id: BaseGameId | None = None
    min_players: Count | None = None
    max_players: Count | None = None
    min_age: Age | None = None
    min_play_time_minutes: Count | None = None
    max_play_time_minutes: Count | None = None
    year: Year | None = None
    genres: Genres | None = None
    publisher: str | None = None


class GameRead(GameCreate):
    """A game as returned by the API."""

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: int
    created_at: datetime
    updated_at: datetime
