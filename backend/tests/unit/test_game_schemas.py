import pytest
from pydantic import ValidationError

from app.schemas.games import GameCreate, GameUpdate


def test_valid_game_is_accepted() -> None:
    game = GameCreate(name="Catan", min_players=3, max_players=4)
    assert game.model_dump() == {
        "name": "Catan",
        "description": None,
        "is_expansion": False,
        "base_game_id": None,
        "min_players": 3,
        "max_players": 4,
        "min_age": None,
        "min_play_time_minutes": None,
        "max_play_time_minutes": None,
        "year": None,
        "genres": [],
        "publisher": None,
    }


def test_base_game_id_without_is_expansion_is_rejected() -> None:
    with pytest.raises(ValidationError, match="base_game_id is only allowed for expansions"):
        GameCreate(name="Seafarers", base_game_id=1)


def test_expansion_with_base_game_id_is_accepted() -> None:
    game = GameCreate(name="Seafarers", is_expansion=True, base_game_id=1)
    assert game.base_game_id == 1


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"min_players": 4, "max_players": 2}, "max_players must be at least min_players"),
        (
            {"min_play_time_minutes": 60, "max_play_time_minutes": 30},
            "max_play_time_minutes must be at least min_play_time_minutes",
        ),
    ],
    ids=["players", "play_time"],
)
def test_range_ending_before_it_starts_is_rejected(fields: dict[str, int], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        GameCreate.model_validate({"name": "Catan", **fields})


def test_genres_are_trimmed_lowercased_and_deduplicated() -> None:
    game = GameCreate.model_validate({"name": "Catan", "genres": [" Co-op", "co-op", "Party"]})
    assert game.genres == ["co-op", "party"]


def test_name_is_stripped() -> None:
    game = GameCreate(name="  Catan ")
    assert game.name == "Catan"


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_invalid_name_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        GameCreate(name=name)


def test_update_rejects_values_outside_the_shared_limits() -> None:
    with pytest.raises(ValidationError):
        GameUpdate.model_validate({"min_players": 0})


def test_update_dumps_only_the_fields_that_were_sent() -> None:
    update = GameUpdate.model_validate({"max_players": 5})
    assert update.model_dump(exclude_unset=True) == {"max_players": 5}
