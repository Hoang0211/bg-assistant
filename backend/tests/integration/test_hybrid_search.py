from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBEDDING_DIMENSION, Chunk, ChunkType, Game, Rulebook
from app.ingestion.embedder import FakeEmbedder
from app.retrieval.hybrid import SearchResult, full_text_search, hybrid_search, vector_search


def _vector(*values: float) -> list[float]:
    """A vector with the given leading values and zeros after them."""
    return [*values, *[0.0] * (EMBEDDING_DIMENSION - len(values))]


async def _add_game(db_session: AsyncSession, name: str, **fields: Any) -> tuple[Game, Rulebook]:
    game = Game(name=name, **fields)
    db_session.add(game)
    await db_session.flush()
    rulebook = Rulebook(
        game_id=game.id,
        filename=f"{name}.pdf",
        storage_path=f"{name}.pdf",
        page_count=10,
        sha256=name.ljust(64, "0"),
    )
    db_session.add(rulebook)
    await db_session.flush()
    return game, rulebook


async def _add_chunk(
    db_session: AsyncSession, rulebook: Rulebook, content: str, embedding: list[float]
) -> Chunk:
    chunk = Chunk(
        rulebook_id=rulebook.id,
        game_id=rulebook.game_id,
        section_path="Rules",
        chunk_type=ChunkType.SECTION,
        page_start=2,
        page_end=3,
        content=content,
        embedding=embedding,
    )
    db_session.add(chunk)
    await db_session.flush()
    return chunk


async def test_vector_search_returns_the_nearest_chunks_first(db_session: AsyncSession) -> None:
    game, rulebook = await _add_game(db_session, "Catan")
    far = await _add_chunk(db_session, rulebook, "far", _vector(0, 1))
    near = await _add_chunk(db_session, rulebook, "near", _vector(1, 0.1))
    middle = await _add_chunk(db_session, rulebook, "middle", _vector(1, 1))

    ids = await vector_search(db_session, _vector(1, 0), [game.id], limit=2)

    assert ids == [near.id, middle.id]
    assert far.id not in ids


async def test_vector_search_returns_only_the_given_games_chunks(
    db_session: AsyncSession,
) -> None:
    game, rulebook = await _add_game(db_session, "Catan")
    _, other_rulebook = await _add_game(db_session, "Azul")
    chunk = await _add_chunk(db_session, rulebook, "Catan", _vector(0, 1))
    await _add_chunk(db_session, other_rulebook, "Azul", _vector(1, 0))

    assert await vector_search(db_session, _vector(1, 0), [game.id], limit=10) == [chunk.id]


async def test_vector_search_finds_a_games_chunks_behind_many_closer_ones(
    db_session: AsyncSession,
) -> None:
    game, rulebook = await _add_game(db_session, "Catan")
    _, other_rulebook = await _add_game(db_session, "Azul")
    far = [await _add_chunk(db_session, rulebook, "Catan", _vector(0, 1)) for _ in range(3)]
    for _ in range(50):
        await _add_chunk(db_session, other_rulebook, "Azul", _vector(1, 0))
    # Rule out every plan but the HNSW index, which would keep only its 40 nearest neighbours,
    # all of them Azul's, and then drop them as another game's.
    for setting in ("enable_seqscan", "enable_bitmapscan", "enable_sort"):
        await db_session.execute(text(f"SET LOCAL {setting} = off"))

    ids = await vector_search(db_session, _vector(1, 0), [game.id], limit=10)

    assert ids == [chunk.id for chunk in far]


async def test_full_text_search_matches_other_forms_of_a_word(db_session: AsyncSession) -> None:
    game, rulebook = await _add_game(db_session, "Catan")
    chunk = await _add_chunk(db_session, rulebook, "Players trade resources.", _vector(1))
    await _add_chunk(db_session, rulebook, "Roll the dice.", _vector(1))

    assert await full_text_search(db_session, "trading", [game.id], limit=10) == [chunk.id]


async def test_full_text_search_matches_chunks_with_any_of_the_words(
    db_session: AsyncSession,
) -> None:
    game, rulebook = await _add_game(db_session, "Catan")
    both = await _add_chunk(db_session, rulebook, "Players trade resources.", _vector(1))
    one = await _add_chunk(db_session, rulebook, "Move the robber.", _vector(1))
    await _add_chunk(db_session, rulebook, "Roll the dice.", _vector(1))

    query = "Can I trade resources with the robber?"
    ids = await full_text_search(db_session, query, [game.id], limit=10)

    assert ids == [both.id, one.id]


async def test_full_text_search_ranks_the_better_match_first(db_session: AsyncSession) -> None:
    game, rulebook = await _add_game(db_session, "Catan")
    once = await _add_chunk(db_session, rulebook, "Trade with the bank.", _vector(1))
    twice = await _add_chunk(db_session, rulebook, "Trade, then trade again.", _vector(1))

    assert await full_text_search(db_session, "trade", [game.id], limit=10) == [twice.id, once.id]


async def test_full_text_search_returns_only_the_given_games_chunks(
    db_session: AsyncSession,
) -> None:
    game, rulebook = await _add_game(db_session, "Catan")
    _, other_rulebook = await _add_game(db_session, "Azul")
    chunk = await _add_chunk(db_session, rulebook, "Trade resources.", _vector(1))
    await _add_chunk(db_session, other_rulebook, "Trade tiles.", _vector(1))

    assert await full_text_search(db_session, "trade", [game.id], limit=10) == [chunk.id]


async def test_hybrid_search_returns_fused_chunks_with_their_games_current_name(
    db_session: AsyncSession,
) -> None:
    embedder = FakeEmbedder()
    base, base_rulebook = await _add_game(db_session, "Catan")
    expansion, expansion_rulebook = await _add_game(
        db_session, "Seafarers", is_expansion=True, base_game_id=base.id
    )
    by_both = await _add_chunk(
        db_session, base_rulebook, "Ships carry trade.", embedder.embed_query("ships")
    )
    by_text = await _add_chunk(db_session, expansion_rulebook, "Ships sail.", _vector(0, 1))
    base.name = "Catan (renamed)"
    await db_session.flush()

    results = await hybrid_search(db_session, embedder, "ships", [base.id, expansion.id])

    assert results == [
        SearchResult(
            chunk_id=by_both.id,
            rulebook_id=base_rulebook.id,
            game_name="Catan (renamed)",
            is_expansion=False,
            section_path="Rules",
            page_start=2,
            page_end=3,
            content="Ships carry trade.",
        ),
        SearchResult(
            chunk_id=by_text.id,
            rulebook_id=expansion_rulebook.id,
            game_name="Seafarers",
            is_expansion=True,
            section_path="Rules",
            page_start=2,
            page_end=3,
            content="Ships sail.",
        ),
    ]
