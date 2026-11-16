from datetime import datetime

from app.config import Settings
from app.evaluation.metrics import Place
from app.evaluation.questions import GoldenQuestion
from app.evaluation.report import format_report
from app.evaluation.retrieval import QuestionResult


def _question(question_id: str, game: str, tags: list[str]) -> GoldenQuestion:
    return GoldenQuestion(
        id=question_id, game=game, question="?", expected=[], answer="", tags=tags
    )


def test_format_report_shows_the_scores_and_each_questions_top_results() -> None:
    settings = Settings(
        embedding_model="bge",
        vector_candidates=30,
        full_text_candidates=30,
        rrf_k=60,
        fused_candidates=20,
        reranker_model="reranker",
        search_results=2,
    )
    results = [
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

    report = format_report(results, settings, chunk_count=12, now=datetime(2026, 11, 15, 9, 5))

    assert report == (
        "# Retrieval eval: 2026-11-15 09:05\n"
        "\n"
        "- Search: hybrid (vector 30, full text 30, RRF k = 60, fused 20), then reranked;"
        " the top 2 are scored\n"
        "- Embedding model: bge\n"
        "- Reranker model: reranker\n"
        "- Chunks in the eval database: 12\n"
        "- A hit is a chunk from an expected rulebook covering an expected page, even if it's"
        " about something else, so a rulebook printed on one page makes all its chunks hits.\n"
        "\n"
        "| Questions | Count | Recall@2 | MRR | nDCG@2 |\n"
        "| --- | --: | --: | --: | --: |\n"
        "| all | 2 | 0.50 | 0.25 | 0.30 |\n"
        "| Base | 1 | 1.00 | 0.50 | 0.60 |\n"
        "| Expansion | 1 | 0.00 | 0.00 | 0.00 |\n"
        "| table | 1 | 1.00 | 0.50 | 0.60 |\n"
        "\n"
        "## Questions\n"
        "\n"
        "| Question | First hit | Top 2 (✓ = hit) |\n"
        "| --- | --: | --- |\n"
        "| q-1 | 2 | a.pdf p. 1, a.pdf pp. 2–3 ✓ |\n"
        "| q-2 | – | b.pdf p. 4 |\n"
    )
