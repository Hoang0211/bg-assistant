import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game
from app.schemas.games import GameCreate, GameFilters, GameUpdate
from app.services.games import (
    GameNotFoundError,
    InvalidExpansionError,
    create_game,
    delete_game,
    get_game,
    list_games,
    update_game,
)


async def add_game(session: AsyncSession, **fields: object) -> Game:
    return await create_game(session, GameCreate.model_validate({"name": "Game", **fields}))


async def test_create_game_stores_a_base_game(db_session: AsyncSession) -> None:
    game = await add_game(db_session)
    game_id = game.id

    db_session.expunge(game)
    stored = await get_game(db_session, game_id)

    assert stored.name == "Game"
    assert stored.is_expansion is False
    assert stored.base_game_id is None


async def test_create_game_links_an_expansion_to_its_base_game(db_session: AsyncSession) -> None:
    base = await add_game(db_session, name="Catan")

    expansion = await add_game(
        db_session, name="Seafarers", is_expansion=True, base_game_id=base.id
    )

    assert expansion.id is not None
    assert expansion.base_game_id == base.id


async def test_create_game_stores_an_unlinked_expansion(db_session: AsyncSession) -> None:
    game = await add_game(db_session, is_expansion=True)
    game_id = game.id

    db_session.expunge(game)
    stored = await get_game(db_session, game_id)

    assert stored.is_expansion is True
    assert stored.base_game_id is None


async def test_create_game_rejects_a_missing_base_game(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidExpansionError, match="does not exist"):
        await add_game(db_session, is_expansion=True, base_game_id=999)


async def test_create_game_rejects_an_expansion_as_base_game(db_session: AsyncSession) -> None:
    base = await add_game(db_session)
    expansion = await add_game(
        db_session, name="Expansion 1", is_expansion=True, base_game_id=base.id
    )

    with pytest.raises(InvalidExpansionError, match="itself an expansion"):
        await add_game(db_session, name="Expansion 2", is_expansion=True, base_game_id=expansion.id)


async def test_get_game_raises_for_an_unknown_id(db_session: AsyncSession) -> None:
    with pytest.raises(GameNotFoundError, match="999"):
        await get_game(db_session, 999)


async def test_list_games_sorts_by_name(db_session: AsyncSession) -> None:
    await add_game(db_session, name="Game A")
    await add_game(db_session, name="Game C")
    await add_game(db_session, name="Game B")

    games = await list_games(db_session, GameFilters())

    assert [game.name for game in games] == ["Game A", "Game B", "Game C"]


async def test_list_games_searches_names_in_any_case(db_session: AsyncSession) -> None:
    await add_game(db_session, name="Game one")
    await add_game(db_session, name="Game two")
    await add_game(db_session, name="Game three")

    games = await list_games(db_session, GameFilters(q="THREE"))

    assert [game.name for game in games] == ["Game three"]


async def test_list_games_treats_wildcards_in_the_search_literally(
    db_session: AsyncSession,
) -> None:
    await add_game(db_session, name="Game")
    await add_game(db_session, name="Game %")

    games = await list_games(db_session, GameFilters(q="%"))

    assert [game.name for game in games] == ["Game %"]


@pytest.mark.parametrize("players", [2, 3, 4])
async def test_list_games_filters_by_player_count_including_the_edges(
    db_session: AsyncSession, players: int
) -> None:
    await add_game(db_session, name="Game 1", min_players=2, max_players=4)
    await add_game(db_session, name="Game 2", min_players=5, max_players=8)

    games = await list_games(db_session, GameFilters(players=players))

    assert [game.name for game in games] == ["Game 1"]


async def test_list_games_player_filter_excludes_unknown_counts(
    db_session: AsyncSession,
) -> None:
    await add_game(db_session, name="Game 1")
    await add_game(db_session, name="Game 2", min_players=5, max_players=8)

    games = await list_games(db_session, GameFilters(players=7))

    assert [game.name for game in games] == ["Game 2"]


async def test_list_games_filters_by_any_of_the_genres(
    db_session: AsyncSession,
) -> None:
    await add_game(db_session, name="Game 1", genres=["party"])
    await add_game(db_session, name="Game 2", genres=["co-op"])
    await add_game(db_session, name="Game 3", genres=["zombie"])

    games = await list_games(db_session, GameFilters(genres=["  Party  ", "CO-OP"]))

    assert [game.name for game in games] == ["Game 1", "Game 2"]


async def test_list_games_filters_by_base_game(db_session: AsyncSession) -> None:
    game_base_1 = await add_game(db_session, name="Game 1")
    game_base_2 = await add_game(db_session, name="Game 2")
    await add_game(db_session, name="Expansion 1", is_expansion=True, base_game_id=game_base_1.id)
    await add_game(db_session, name="Expansion 2", is_expansion=True, base_game_id=game_base_2.id)

    games = await list_games(db_session, GameFilters(base_game_id=game_base_1.id))

    assert [game.name for game in games] == ["Expansion 1"]


async def test_list_games_requires_every_filter_to_match(db_session: AsyncSession) -> None:
    await add_game(db_session, name="Game 1", min_players=2, max_players=4, genres=["party"])
    await add_game(db_session, name="Game 2", min_players=5, max_players=8, genres=["party"])
    await add_game(db_session, name="Game 3", min_players=2, max_players=4, genres=["zombie"])

    games = await list_games(db_session, GameFilters(players=3, genres=["party"]))

    assert [game.name for game in games] == ["Game 1"]


async def test_update_game_changes_only_the_fields_sent(db_session: AsyncSession) -> None:
    game = await add_game(db_session, min_players=2, max_players=4)
    game_id = game.id

    await update_game(db_session, game, GameUpdate(max_players=6))
    db_session.expunge(game)
    stored = await get_game(db_session, game_id)

    assert stored.name == "Game"
    assert stored.min_players == 2
    assert stored.max_players == 6


async def test_update_game_rejects_a_range_invalid_with_stored_values(
    db_session: AsyncSession,
) -> None:
    game = await add_game(db_session, min_players=4, max_players=6)

    with pytest.raises(ValidationError, match="max_players must be at least min_players"):
        await update_game(db_session, game, GameUpdate(max_players=2))


async def test_update_game_rejects_null_for_a_required_field(db_session: AsyncSession) -> None:
    game = await add_game(db_session)

    with pytest.raises(ValidationError, match="name"):
        await update_game(db_session, game, GameUpdate(name=None))


async def test_update_game_rejects_a_missing_base_game(db_session: AsyncSession) -> None:
    game = await add_game(db_session)

    with pytest.raises(InvalidExpansionError, match="does not exist"):
        await update_game(db_session, game, GameUpdate(is_expansion=True, base_game_id=999))


async def test_game_with_expansions_cannot_become_expansion(db_session: AsyncSession) -> None:
    base = await add_game(db_session)
    await add_game(db_session, name="Expansion", is_expansion=True, base_game_id=base.id)

    with pytest.raises(InvalidExpansionError, match="cannot become an expansion"):
        await update_game(db_session, base, GameUpdate(is_expansion=True))


async def test_update_game_renames_a_linked_expansion(db_session: AsyncSession) -> None:
    base = await add_game(db_session)
    expansion = await add_game(
        db_session, name="Expansion", is_expansion=True, base_game_id=base.id
    )

    await update_game(db_session, expansion, GameUpdate(name="Expansion of Game"))

    assert expansion.name == "Expansion of Game"


async def test_update_game_turns_an_expansion_into_a_base_game(db_session: AsyncSession) -> None:
    base = await add_game(db_session)
    expansion = await add_game(
        db_session, name="Expansion", is_expansion=True, base_game_id=base.id
    )

    await update_game(db_session, expansion, GameUpdate(is_expansion=False, base_game_id=None))

    assert expansion.is_expansion is False
    assert expansion.base_game_id is None


async def test_delete_game_removes_the_game(db_session: AsyncSession) -> None:
    game = await add_game(db_session)

    await delete_game(db_session, game)

    with pytest.raises(GameNotFoundError):
        await get_game(db_session, game.id)
