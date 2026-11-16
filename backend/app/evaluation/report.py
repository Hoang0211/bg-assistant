"""The retrieval eval's Markdown report."""

from datetime import datetime

from app.config import Settings
from app.evaluation.metrics import Place
from app.evaluation.retrieval import QuestionResult


def _score_row(label: str, results: list[QuestionResult]) -> str:
    count = len(results)
    mean_recall = sum(result.recall for result in results) / count
    mrr = sum(result.reciprocal_rank for result in results) / count
    mean_ndcg = sum(result.ndcg for result in results) / count
    return f"| {label} | {count} | {mean_recall:.2f} | {mrr:.2f} | {mean_ndcg:.2f} |"


def _first_hit(hits: list[bool]) -> str:
    return next((str(rank) for rank, hit in enumerate(hits, start=1) if hit), "–")


def _place(place: Place, hit: bool) -> str:
    pages = (
        f"p. {place.page_start}"
        if place.page_start == place.page_end
        else f"pp. {place.page_start}–{place.page_end}"
    )
    return f"{place.file} {pages}{' ✓' if hit else ''}"


def format_report(
    results: list[QuestionResult], settings: Settings, chunk_count: int, now: datetime
) -> str:
    """Scores for all questions, each game and each tag, then every question's top results."""
    k = settings.search_results
    games = list(dict.fromkeys(result.question.game for result in results))  # in question order
    tags = sorted({tag for result in results for tag in result.question.tags})
    lines = [
        f"# Retrieval eval: {now:%Y-%m-%d %H:%M}",
        "",
        f"- Search: hybrid (vector {settings.vector_candidates}, full text "
        f"{settings.full_text_candidates}, RRF k = {settings.rrf_k}, fused "
        f"{settings.fused_candidates}); the top {k} are scored",
        f"- Embedding model: {settings.embedding_model}",
        f"- Chunks in the eval database: {chunk_count}",
        "- A hit is a chunk from an expected rulebook covering an expected page, even if it's"
        " about something else, so a rulebook printed on one page makes all its chunks hits.",
        "",
        f"| Questions | Count | Recall@{k} | MRR | nDCG@{k} |",
        "| --- | --: | --: | --: | --: |",
        _score_row("all", results),
        *[_score_row(game, [r for r in results if r.question.game == game]) for game in games],
        *[_score_row(tag, [r for r in results if tag in r.question.tags]) for tag in tags],
        "",
        "## Questions",
        "",
        f"| Question | First hit | Top {k} (✓ = hit) |",
        "| --- | --: | --- |",
    ]
    for result in results:
        top = ", ".join(
            _place(place, hit) for place, hit in zip(result.places, result.hits, strict=True)
        )
        lines.append(f"| {result.question.id} | {_first_hit(result.hits)} | {top} |")
    return "\n".join(lines) + "\n"
