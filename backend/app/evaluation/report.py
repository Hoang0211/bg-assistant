"""The retrieval eval's Markdown report."""

from datetime import datetime

from app.config import Settings
from app.evaluation.metrics import Place
from app.evaluation.retrieval import QuestionResult

# A question's result from hybrid search and from hybrid search reranked.
_Pair = tuple[QuestionResult, QuestionResult]


def _scores(results: list[QuestionResult]) -> str:
    count = len(results)
    mean_recall = sum(result.recall for result in results) / count
    mrr = sum(result.reciprocal_rank for result in results) / count
    mean_ndcg = sum(result.ndcg for result in results) / count
    return f"{mean_recall:.2f} | {mrr:.2f} | {mean_ndcg:.2f}"


def _score_row(label: str, pairs: list[_Pair]) -> str:
    hybrid = [hybrid for hybrid, _ in pairs]
    reranked = [reranked for _, reranked in pairs]
    return f"| {label} | {len(pairs)} | {_scores(hybrid)} | {_scores(reranked)} |"


def _first_hit(hits: list[bool]) -> str:
    return next((str(rank) for rank, hit in enumerate(hits, start=1) if hit), "–")


def _place(place: Place, hit: bool) -> str:
    pages = (
        f"p. {place.page_start}"
        if place.page_start == place.page_end
        else f"pp. {place.page_start}–{place.page_end}"
    )
    return f"{place.file} {pages}{' ✓' if hit else ''}"


def _top(result: QuestionResult) -> str:
    return ", ".join(
        _place(place, hit) for place, hit in zip(result.places, result.hits, strict=True)
    )


def format_report(
    hybrid: list[QuestionResult],
    reranked: list[QuestionResult],
    settings: Settings,
    chunk_count: int,
    now: datetime,
) -> str:
    """Scores without and with reranking for all, each game and each tag; each question's top."""
    k = settings.search_results
    pairs = list(zip(hybrid, reranked, strict=True))
    games = list(dict.fromkeys(result.question.game for result in hybrid))  # in question order
    tags = sorted({tag for result in hybrid for tag in result.question.tags})
    lines = [
        f"# Retrieval eval: {now:%Y-%m-%d %H:%M}",
        "",
        f"- Parser: {settings.pdf_parser}",
        f"- Hybrid search: vector {settings.vector_candidates}, full text "
        f"{settings.full_text_candidates}, RRF k = {settings.rrf_k}",
        f"- Reranked: hybrid search's top {settings.fused_candidates}, reranked by "
        f"{settings.reranker_model}",
        f"- Embedding model: {settings.embedding_model}",
        f"- Scored: each search's top {k}",
        f"- Chunks in the eval database: {chunk_count}",
        "- A hit is a chunk from an expected rulebook covering an expected page, even if it's"
        " about something else, so a rulebook printed on one page makes all its chunks hits.",
        "",
        f"| Questions | Count | Hybrid Recall@{k} | Hybrid MRR | Hybrid nDCG@{k} "
        f"| Reranked Recall@{k} | Reranked MRR | Reranked nDCG@{k} |",
        "| --- | --: | --: | --: | --: | --: | --: | --: |",
        _score_row("all", pairs),
        *[_score_row(game, [p for p in pairs if p[0].question.game == game]) for game in games],
        *[_score_row(tag, [p for p in pairs if tag in p[0].question.tags]) for tag in tags],
        "",
        "## Questions",
        "",
        f"| Question | Hybrid first hit | Reranked first hit | Hybrid top {k} (✓ = hit) "
        f"| Reranked top {k} |",
        "| --- | --: | --: | --- | --- |",
    ]
    for hybrid_result, reranked_result in pairs:
        lines.append(
            f"| {hybrid_result.question.id} | {_first_hit(hybrid_result.hits)} "
            f"| {_first_hit(reranked_result.hits)} | {_top(hybrid_result)} "
            f"| {_top(reranked_result)} |"
        )
    return "\n".join(lines) + "\n"
