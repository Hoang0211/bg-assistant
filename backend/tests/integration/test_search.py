from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBEDDING_DIMENSION, Chunk, ChunkType, Game, Rulebook
from app.ingestion.embedder import FakeEmbedder
from app.retrieval.reranker import FakeReranker
from app.retrieval.search import search

QUERY = "Who goes first in a trade?"


async def _add_rulebook(db_session: AsyncSession) -> Rulebook:
    game = Game(name="Catan")
    db_session.add(game)
    await db_session.flush()
    rulebook = Rulebook(
        game_id=game.id,
        filename="Catan.pdf",
        storage_path="Catan.pdf",
        page_count=10,
        sha256="0" * 64,
    )
    db_session.add(rulebook)
    await db_session.flush()
    return rulebook


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


async def _add_candidates(db_session: AsyncSession, embedder: FakeEmbedder) -> Rulebook:
    """Three chunks that hybrid search and the fake reranker put in different orders."""
    query_vector = embedder.embed_query(QUERY)
    rulebook = await _add_rulebook(db_session)
    # Hybrid search ranks these by distance to the query, since full-text search drops the stop
    # words they share with it ("who", "in", "a"); the fake reranker counts those words too.
    await _add_chunk(db_session, rulebook, "Setup.", query_vector)
    await _add_chunk(
        db_session, rulebook, "Who plays in a team?", [1.0, *[0.0] * (EMBEDDING_DIMENSION - 1)]
    )
    await _add_chunk(db_session, rulebook, "It is a game.", [-value for value in query_vector])
    return rulebook


async def test_search_returns_the_best_scored_candidates_first(db_session: AsyncSession) -> None:
    embedder = FakeEmbedder()
    rulebook = await _add_candidates(db_session, embedder)

    results = await search(db_session, embedder, FakeReranker(), QUERY, [rulebook.game_id], limit=2)

    assert [result.content for result in results] == ["Who plays in a team?", "It is a game."]


async def test_search_without_a_reranker_keeps_the_hybrid_order(db_session: AsyncSession) -> None:
    embedder = FakeEmbedder()
    rulebook = await _add_candidates(db_session, embedder)

    results = await search(db_session, embedder, None, QUERY, [rulebook.game_id], limit=2)

    assert [result.content for result in results] == ["Setup.", "Who plays in a team?"]
