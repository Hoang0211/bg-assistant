from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBEDDING_DIMENSION, Chunk, ChunkType, Game, Rulebook
from app.ingestion.embedder import FakeEmbedder
from app.retrieval.reranker import FakeReranker
from app.retrieval.search import search


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


async def test_search_returns_the_best_scored_candidates_first(db_session: AsyncSession) -> None:
    embedder = FakeEmbedder()
    query = "Who goes first in a trade?"
    query_vector = embedder.embed_query(query)
    rulebook = await _add_rulebook(db_session)
    # Hybrid search ranks these by distance to the query (none has every word, so full text
    # finds none); the fake reranker by how many of the query's words they contain.
    await _add_chunk(db_session, rulebook, "Setup.", query_vector)
    first = await _add_chunk(
        db_session,
        rulebook,
        "The youngest player goes first.",
        [1.0, *[0.0] * (EMBEDDING_DIMENSION - 1)],
    )
    trade = await _add_chunk(
        db_session, rulebook, "Trade cards.", [-value for value in query_vector]
    )

    results = await search(db_session, embedder, FakeReranker(), query, [rulebook.game_id], limit=2)

    # Without reranking, the top 2 would be setup and first.
    assert [result.chunk_id for result in results] == [first.id, trade.id]
