"""The search chat and the eval use: hybrid search's candidates, reranked if a reranker is given."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.embedder import Embedder
from app.retrieval.hybrid import SearchResult, hybrid_search
from app.retrieval.reranker import Reranker


async def search(
    session: AsyncSession,
    embedder: Embedder,
    reranker: Reranker | None,
    query: str,
    game_ids: list[int],
    limit: int,
) -> list[SearchResult]:
    """The given games' chunks that best answer the query, best first."""
    candidates = await hybrid_search(session, embedder, query, game_ids)
    if reranker is None:
        return candidates[:limit]
    # Scoring runs the model, so it's kept off the event loop.
    scores = await asyncio.to_thread(
        reranker.score, query, [candidate.content for candidate in candidates]
    )
    # sorted() is stable, so equal scores keep hybrid search's order.
    ranked = sorted(zip(scores, candidates, strict=True), key=lambda pair: pair[0], reverse=True)
    return [candidate for _, candidate in ranked[:limit]]
