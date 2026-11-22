import math
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EMBEDDING_DIMENSION, Chunk, ChunkType, Game, Rulebook
from app.evaluation.metrics import Place
from app.evaluation.questions import ExpectedPlace, GoldenQuestion
from app.evaluation.retrieval import QuestionResult, evaluate_question, family_game_ids
from app.ingestion.embedder import FakeEmbedder

QUESTION = GoldenQuestion(
    id="q-1",
    game="Base",
    question="Who goes first?",
    expected=[ExpectedPlace(file="Base.pdf", pages=[2])],
    answer="The youngest player.",
    tags=[],
)

# nDCG's weight for a hit at rank 2.
HIT_AT_2 = 1 / math.log2(3)


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
    db_session: AsyncSession,
    rulebook: Rulebook,
    pages: tuple[int, int],
    content: str,
    embedding: list[float],
) -> None:
    db_session.add(
        Chunk(
            rulebook_id=rulebook.id,
            game_id=rulebook.game_id,
            section_path="Rules",
            chunk_type=ChunkType.SECTION,
            page_start=pages[0],
            page_end=pages[1],
            content=content,
            embedding=embedding,
        )
    )
    await db_session.flush()


async def _add_ranked_chunks(db_session: AsyncSession, embedder: FakeEmbedder) -> None:
    """A miss and two hits, which hybrid search ranks miss first."""
    query = embedder.embed_query(QUESTION.question)
    _, rulebook = await _add_game(db_session, "Base")
    # Hybrid search ranks them by distance to the query: the miss, then one hit, then the other.
    # Full-text search drops "Who is it?" as all stop words, so only the distance counts.
    await _add_chunk(db_session, rulebook, (5, 5), "Setup.", query)
    await _add_chunk(
        db_session, rulebook, (2, 3), "Who is it?", [1.0, *[0.0] * (EMBEDDING_DIMENSION - 1)]
    )
    await _add_chunk(db_session, rulebook, (1, 2), "Setup.", [-value for value in query])


async def test_family_game_ids_returns_a_base_game_and_its_expansions(
    db_session: AsyncSession,
) -> None:
    base, _ = await _add_game(db_session, "Base")
    first, _ = await _add_game(db_session, "First", is_expansion=True, base_game_id=base.id)
    second, _ = await _add_game(db_session, "Second", is_expansion=True, base_game_id=base.id)
    await _add_game(db_session, "Other")

    assert await family_game_ids(db_session, "Base") == [base.id, first.id, second.id]


async def test_family_game_ids_returns_the_whole_family_for_an_expansion(
    db_session: AsyncSession,
) -> None:
    base, _ = await _add_game(db_session, "Base")
    first, _ = await _add_game(db_session, "First", is_expansion=True, base_game_id=base.id)
    second, _ = await _add_game(db_session, "Second", is_expansion=True, base_game_id=base.id)
    await _add_game(db_session, "Other")

    assert await family_game_ids(db_session, "Second") == [base.id, first.id, second.id]


async def test_evaluate_question_scores_the_top_k_results(db_session: AsyncSession) -> None:
    embedder = FakeEmbedder()
    await _add_ranked_chunks(db_session, embedder)

    result = await evaluate_question(db_session, embedder, QUESTION, k=2)

    assert result == QuestionResult(
        question=QUESTION,
        places=[Place("Base.pdf", 5, 5), Place("Base.pdf", 2, 3)],
        hits=[False, True],
        recall=1.0,
        reciprocal_rank=0.5,
        ndcg=HIT_AT_2 / (1 + HIT_AT_2),
    )
