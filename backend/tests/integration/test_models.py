from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, ChunkType, Game, Rulebook, RulebookStatus


def make_rulebook(game_id: int, sha256: str = "a" * 64) -> Rulebook:
    return Rulebook(
        game_id=game_id,
        filename="rules.pdf",
        storage_path="data/uploads/rules.pdf",
        page_count=12,
        sha256=sha256,
    )


async def add_rulebook(db_session: AsyncSession) -> Rulebook:
    game = Game(name="Game")
    db_session.add(game)
    await db_session.flush()
    rulebook = make_rulebook(game.id)
    db_session.add(rulebook)
    await db_session.flush()
    return rulebook


def make_chunk(rulebook: Rulebook, **fields: Any) -> Chunk:
    values: dict[str, Any] = {
        "rulebook_id": rulebook.id,
        "game_id": rulebook.game_id,
        "section_path": "Turn Order > Trading",
        "chunk_type": ChunkType.SECTION,
        "page_start": 3,
        "page_end": 3,
        "content": "Players trade resources during their turn.",
        "embedding": [0.0] * 768,
    }
    return Chunk(**{**values, **fields})


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


async def test_new_chunk_is_found_by_full_text_search(db_session: AsyncSession) -> None:
    rulebook = await add_rulebook(db_session)
    chunk = make_chunk(rulebook)
    db_session.add(chunk)
    await db_session.flush()

    found = await db_session.scalars(
        select(Chunk.id).where(
            Chunk.tsv.bool_op("@@")(func.websearch_to_tsquery("english", "trading"))
        )
    )

    assert list(found) == [chunk.id]


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"page_start": 0}, "ck_chunks_page_start_positive"),
        ({"page_start": 5, "page_end": 4}, "ck_chunks_page_range"),
    ],
    ids=["page_start", "page_range"],
)
async def test_invalid_chunk_pages_are_rejected(
    db_session: AsyncSession, fields: dict[str, Any], constraint: str
) -> None:
    rulebook = await add_rulebook(db_session)
    db_session.add(make_chunk(rulebook, **fields))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_unknown_chunk_type_is_rejected(db_session: AsyncSession) -> None:
    rulebook = await add_rulebook(db_session)
    db_session.add(make_chunk(rulebook, chunk_type="asdf"))
    with pytest.raises(IntegrityError, match="ck_chunks_chunktype"):
        await db_session.flush()


async def test_wrong_length_embedding_is_rejected(db_session: AsyncSession) -> None:
    rulebook = await add_rulebook(db_session)
    db_session.add(make_chunk(rulebook, embedding=[0.0] * 3))
    with pytest.raises(DataError, match="expected 768 dimensions"):
        await db_session.flush()


async def test_chunk_cannot_belong_to_a_different_game_from_its_rulebook(
    db_session: AsyncSession,
) -> None:
    rulebook = await add_rulebook(db_session)
    other_game = Game(name="Other game")
    db_session.add(other_game)
    await db_session.flush()

    db_session.add(make_chunk(rulebook, game_id=other_game.id))
    with pytest.raises(IntegrityError, match="fk_chunks_rulebook_id_rulebooks"):
        await db_session.flush()


async def test_moving_a_rulebook_moves_its_chunks(
    db_session: AsyncSession,
) -> None:
    rulebook = await add_rulebook(db_session)
    chunks = [make_chunk(rulebook), make_chunk(rulebook)]
    other_game = Game(name="Other game")
    db_session.add_all([*chunks, other_game])
    await db_session.flush()

    rulebook.game_id = other_game.id
    await db_session.flush()

    for chunk in chunks:
        await db_session.refresh(chunk)
    assert [chunk.game_id for chunk in chunks] == [other_game.id, other_game.id]


async def test_deleting_a_rulebook_deletes_its_chunks(
    db_session: AsyncSession,
) -> None:
    rulebook = await add_rulebook(db_session)
    chunks = [make_chunk(rulebook), make_chunk(rulebook)]
    db_session.add_all(chunks)
    await db_session.flush()
    chunk_ids = [chunk.id for chunk in chunks]

    await db_session.delete(rulebook)
    await db_session.flush()

    remaining = await db_session.scalars(select(Chunk.id).where(Chunk.id.in_(chunk_ids)))
    assert list(remaining) == []
