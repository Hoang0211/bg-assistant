from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook, RulebookStatus


def make_rulebook(game_id: int, sha256: str = "a" * 64) -> Rulebook:
    return Rulebook(
        game_id=game_id,
        filename="rules.pdf",
        storage_path="data/uploads/rules.pdf",
        page_count=12,
        sha256=sha256,
    )


async def test_new_game_and_rulebook_get_database_defaults(db_session: AsyncSession) -> None:
    game = Game(name="Catan")
    db_session.add(game)
    await db_session.flush()

    rulebook = make_rulebook(game.id)
    db_session.add(rulebook)
    await db_session.flush()

    await db_session.refresh(game)
    await db_session.refresh(rulebook)
    assert game.genres == []
    assert game.is_expansion is False
    assert game.created_at is not None
    assert game.updated_at is not None
    assert rulebook.status == RulebookStatus.UPLOADED


@pytest.mark.parametrize(
    "fields",
    [
        {"min_players": 4, "max_players": 2},
        {"min_play_time_minutes": 60, "max_play_time_minutes": 30},
        {"min_players": 0},
        {"min_play_time_minutes": 0},
        {"min_age": -1},
    ],
    ids=["players_range", "play_time_range", "min_players", "min_play_time", "min_age"],
)
async def test_invalid_numbers_are_rejected(
    db_session: AsyncSession, fields: dict[str, Any]
) -> None:
    db_session.add(Game(name="Game", **fields))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_game_cannot_be_its_own_expansion(db_session: AsyncSession) -> None:
    game = Game(name="Game")
    db_session.add(game)
    await db_session.flush()

    game.is_expansion = True
    game.base_game_id = game.id
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_base_game_cannot_have_a_base_game(db_session: AsyncSession) -> None:
    game1 = Game(name="Game 1")
    db_session.add(game1)
    await db_session.flush()

    game2 = Game(name="Game 2", base_game_id=game1.id)
    db_session.add(game2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_duplicate_rulebook_sha256_is_rejected(db_session: AsyncSession) -> None:
    game = Game(name="Game")
    db_session.add(game)
    await db_session.flush()

    rulebook1 = make_rulebook(game.id)
    db_session.add(rulebook1)

    rulebook2 = make_rulebook(game.id)
    db_session.add(rulebook2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_a_game_deletes_its_rulebooks(db_session: AsyncSession) -> None:
    game = Game(name="Game")
    db_session.add(game)
    await db_session.flush()

    rulebook = make_rulebook(game.id)
    db_session.add(rulebook)
    await db_session.flush()

    rulebook_id = rulebook.id
    await db_session.delete(game)
    await db_session.flush()

    db_session.expunge(rulebook)
    assert await db_session.get(Rulebook, rulebook_id) is None


async def test_deleting_a_base_game_unlinks_its_expansion(db_session: AsyncSession) -> None:
    game = Game(name="Game")
    db_session.add(game)
    await db_session.flush()

    expansion = Game(name="Expansion", is_expansion=True, base_game_id=game.id)
    db_session.add(expansion)
    await db_session.flush()

    await db_session.delete(game)
    await db_session.flush()

    await db_session.refresh(expansion)
    assert expansion.base_game_id is None
    assert expansion.is_expansion is True


async def test_unknown_rulebook_status_is_rejected(db_session: AsyncSession) -> None:
    game = Game(name="Game")
    db_session.add(game)
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO rulebooks "
                "(game_id, filename, storage_path, page_count, sha256, status) "
                "VALUES (:game_id, 'rules.pdf', 'data/uploads/rules.pdf', 12, :sha256, 'archived')"
            ),
            {"game_id": game.id, "sha256": "b" * 64},
        )
