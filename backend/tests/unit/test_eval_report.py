from datetime import datetime

from app.config import Settings
from app.evaluation.metrics import Place
from app.evaluation.questions import GoldenQuestion
from app.evaluation.report import EvalRun, format_report
from app.evaluation.retrieval import QuestionResult

SETTINGS = Settings(
    embedding_model="bge",
    vector_candidates=30,
    full_text_candidates=30,
    rrf_k=60,
    fused_candidates=20,
    reranker_model="reranker",
    search_results=2,
)

NOW = datetime(2026, 11, 15, 9, 5)

SEARCH_LINES = (
    "- Hybrid search: vector 30, full text 30, RRF k = 60\n"
    "- Reranked: hybrid search's top 20, reranked by reranker\n"
    "- Embedding model: bge\n"
    "- Scored: each search's top 2\n"
)

HIT_NOTE = (
    "- A hit is a chunk from an expected rulebook covering an expected page, even if it's"
    " about something else, so a rulebook printed on one page makes all its chunks hits.\n"
)


def _question(question_id: str, game: str, tags: list[str]) -> GoldenQuestion:
    return GoldenQuestion(
        id=question_id, game=game, question="?", expected=[], answer="", tags=tags
    )


def test_format_report_shows_the_scores_and_each_questions_top_results() -> None:
    hybrid = [
        QuestionResult(
            question=_question("q-1", "Base", ["table"]),
            places=[Place("a.pdf", 1, 1), Place("a.pdf", 2, 3)],
            hits=[False, True],
            recall=1.0,
            reciprocal_rank=0.5,
            ndcg=0.6,
        ),
        QuestionResult(
            question=_question("q-2", "Expansion", []),
            places=[Place("b.pdf", 4, 4)],
            hits=[False],
            recall=0.0,
            reciprocal_rank=0.0,
            ndcg=0.0,
        ),
    ]
    reranked = [
        QuestionResult(
            question=_question("q-1", "Base", ["table"]),
            places=[Place("a.pdf", 2, 3), Place("a.pdf", 1, 1)],
            hits=[True, False],
            recall=1.0,
            reciprocal_rank=1.0,
            ndcg=0.9,
        ),
        QuestionResult(
            question=_question("q-2", "Expansion", []),
            places=[Place("b.pdf", 4, 4)],
            hits=[False],
            recall=0.0,
            reciprocal_rank=0.0,
            ndcg=0.0,
        ),
    ]

    report = format_report(EvalRun(12, hybrid, reranked), SETTINGS, NOW)

    assert report == (
        "# Retrieval eval: 2026-11-15 09:05\n"
        "\n"
        f"{SEARCH_LINES}"
        "- Chunks in the eval database: 12\n"
        f"{HIT_NOTE}"
        "\n"
        "| Questions | Count | Hybrid Recall@2 | Hybrid MRR | Hybrid nDCG@2"
        " | Reranked Recall@2 | Reranked MRR | Reranked nDCG@2 |\n"
        "| --- | --: | --: | --: | --: | --: | --: | --: |\n"
        "| all | 2 | 0.50 | 0.25 | 0.30 | 0.50 | 0.50 | 0.45 |\n"
        "| Base | 1 | 1.00 | 0.50 | 0.60 | 1.00 | 1.00 | 0.90 |\n"
        "| Expansion | 1 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |\n"
        "| table | 1 | 1.00 | 0.50 | 0.60 | 1.00 | 1.00 | 0.90 |\n"
        "\n"
        "## Questions\n"
        "\n"
        "| Question | Hybrid first hit | Reranked first hit | Hybrid top 2 (✓ = hit)"
        " | Reranked top 2 |\n"
        "| --- | --: | --: | --- | --- |\n"
        "| q-1 | 2 | 1 | a.pdf p. 1, a.pdf pp. 2–3 ✓ | a.pdf pp. 2–3 ✓, a.pdf p. 1 |\n"
        "| q-2 | – | – | b.pdf p. 4 | b.pdf p. 4 |\n"
    )
