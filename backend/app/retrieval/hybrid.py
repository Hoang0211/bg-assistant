"""Hybrid search over chosen games' chunks: vector and full-text search merged with RRF."""

import asyncio
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk, Game
from app.ingestion.embedder import Embedder


@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    rulebook_id: int
    game_name: str  # read through a join, so it's always the game's current name
    is_expansion: bool
    section_path: str
    page_start: int
    page_end: int
    content: str


async def vector_search(
    session: AsyncSession, query_vector: list[float], game_ids: list[int], limit: int
) -> list[int]:
    """Chunk ids of the given games, nearest to the query vector first (cosine distance)."""
    ids = await session.scalars(
        select(Chunk.id)
        .where(Chunk.game_id.in_(game_ids))
        .order_by(Chunk.embedding.cosine_distance(query_vector), Chunk.id)
        .limit(limit)
    )
    return list(ids)


async def full_text_search(
    session: AsyncSession, query: str, game_ids: list[int], limit: int
) -> list[int]:
    """Chunk ids of the given games that have any of the query's words, best match first."""
    # "or" between the words makes a chunk match with any of them, not only with all; stop words
    # are still dropped and other forms of a word still match.
    tsquery = func.websearch_to_tsquery("english", " or ".join(re.findall(r"\w+", query)))
    ids = await session.scalars(
        select(Chunk.id)
        .where(Chunk.game_id.in_(game_ids), Chunk.tsv.bool_op("@@")(tsquery))
        # ts_rank counts the matches; ts_rank_cd's word-closeness ranked OR matches worse.
        .order_by(func.ts_rank(Chunk.tsv, tsquery).desc(), Chunk.id)
        .limit(limit)
    )
    return list(ids)


def reciprocal_rank_fusion(rankings: list[list[int]], k: int) -> list[int]:
    """Merge rankings: each id scores 1 / (k + rank) per list it's in; highest total first."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
    # sorted() is stable, so equal scores keep the order they were first seen in.
    return sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)


async def _load(session: AsyncSession, chunk_ids: list[int]) -> list[SearchResult]:
    rows = await session.execute(
        select(
            Chunk.id,
            Chunk.rulebook_id,
            Game.name,
            Game.is_expansion,
            Chunk.section_path,
            Chunk.page_start,
            Chunk.page_end,
            Chunk.content,
        )
        .join(Game, Game.id == Chunk.game_id)
        .where(Chunk.id.in_(chunk_ids))
    )
    results = {row[0]: SearchResult(*row) for row in rows}
    return [results[chunk_id] for chunk_id in chunk_ids]


async def hybrid_search(
    session: AsyncSession, embedder: Embedder, query: str, game_ids: list[int]
) -> list[SearchResult]:
    """The fused candidates for a question, searching only the given games' chunks."""
    settings = get_settings()
    # Embedding runs the model, so it's kept off the event loop.
    query_vector = await asyncio.to_thread(embedder.embed_query, query)
    vector_ids = await vector_search(session, query_vector, game_ids, settings.vector_candidates)
    text_ids = await full_text_search(session, query, game_ids, settings.full_text_candidates)
    fused = reciprocal_rank_fusion([vector_ids, text_ids], settings.rrf_k)
    return await _load(session, fused[: settings.fused_candidates])
