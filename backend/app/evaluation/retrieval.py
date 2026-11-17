"""Runs each golden question through the search and scores its top results."""

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Game, Rulebook
from app.evaluation.metrics import Place, is_hit, ndcg, recall, reciprocal_rank
from app.evaluation.questions import GoldenQuestion
from app.ingestion.embedder import Embedder
from app.retrieval.reranker import Reranker
from app.retrieval.search import search


@dataclass(frozen=True)
class QuestionResult:
    question: GoldenQuestion
    places: list[Place]  # where each of the top results is printed, best first
    hits: list[bool]
    recall: float
    reciprocal_rank: float
    ndcg: float


async def family_game_ids(session: AsyncSession, game_name: str) -> list[int]:
    """The ids of the named game's base game and all of that base game's expansions."""
    game_id, base_game_id = (
        await session.execute(select(Game.id, Game.base_game_id).where(Game.name == game_name))
    ).one()
    base_id = base_game_id or game_id
    ids = await session.scalars(
        select(Game.id)
        .where(or_(Game.id == base_id, Game.base_game_id == base_id))
        .order_by(Game.id)
    )
    return list(ids)


async def _places(session: AsyncSession, game_ids: list[int]) -> dict[int, Place]:
    rows = await session.execute(
        select(Chunk.id, Rulebook.filename, Chunk.page_start, Chunk.page_end)
        .join(Rulebook, Rulebook.id == Chunk.rulebook_id)
        .where(Chunk.game_id.in_(game_ids))
    )
    return {chunk_id: Place(file, start, end) for chunk_id, file, start, end in rows}


async def evaluate_question(
    session: AsyncSession,
    embedder: Embedder,
    reranker: Reranker | None,
    question: GoldenQuestion,
    k: int,
) -> QuestionResult:
    """Search the question's game family and score the top k results."""
    game_ids = await family_game_ids(session, question.game)
    places = await _places(session, game_ids)
    results = await search(session, embedder, reranker, question.question, game_ids, limit=k)
    top = [places[result.chunk_id] for result in results]
    hits = [is_hit(place, question.expected) for place in top]
    relevant_count = sum(is_hit(place, question.expected) for place in places.values())
    return QuestionResult(
        question=question,
        places=top,
        hits=hits,
        recall=recall(hits),
        reciprocal_rank=reciprocal_rank(hits),
        ndcg=ndcg(hits, relevant_count, k),
    )
