"""The retrieval eval's Markdown reports: one parser's, and two parsers side by side."""

from dataclasses import dataclass
from datetime import datetime

from app.config import Settings
from app.evaluation.metrics import Place
from app.evaluation.retrieval import QuestionResult


@dataclass(frozen=True)
class ParserResults:
    """Every golden question searched in one parser's eval database, without and with reranking."""

    parser: str
    chunk_count: int
    hybrid: list[QuestionResult]
    reranked: list[QuestionResult]


# One question's results from two searches, or from two parsers' databases.
_Pair = tuple[QuestionResult, QuestionResult]

_HIT_NOTE = (
    "- A hit is a chunk from an expected rulebook covering an expected page, even if it's"
    " about something else, so a rulebook printed on one page makes all its chunks hits."
)


def _search_lines(settings: Settings) -> list[str]:
    return [
        f"- Hybrid search: vector {settings.vector_candidates}, full text "
        f"{settings.full_text_candidates}, RRF k = {settings.rrf_k}",
        f"- Reranked: hybrid search's top {settings.fused_candidates}, reranked by "
        f"{settings.reranker_model}",
        f"- Embedding model: {settings.embedding_model}",
        f"- Scored: each search's top {settings.search_results}",
    ]


def _scores(results: list[QuestionResult]) -> str:
    count = len(results)
    mean_recall = sum(result.recall for result in results) / count
    mrr = sum(result.reciprocal_rank for result in results) / count
    mean_ndcg = sum(result.ndcg for result in results) / count
    return f"{mean_recall:.2f} | {mrr:.2f} | {mean_ndcg:.2f}"


def _score_row(label: str, pairs: list[_Pair]) -> str:
    first = [result for result, _ in pairs]
    second = [result for _, result in pairs]
    return f"| {label} | {len(pairs)} | {_scores(first)} | {_scores(second)} |"


def _score_table(names: tuple[str, str], pairs: list[_Pair], k: int) -> list[str]:
    """Two sets of results' scores side by side, for all questions, each game and each tag."""
    first, second = names
    games = list(dict.fromkeys(result.question.game for result, _ in pairs))  # in question order
    tags = sorted({tag for result, _ in pairs for tag in result.question.tags})
    return [
        f"| Questions | Count | {first} Recall@{k} | {first} MRR | {first} nDCG@{k} "
        f"| {second} Recall@{k} | {second} MRR | {second} nDCG@{k} |",
        "| --- | --: | --: | --: | --: | --: | --: | --: |",
        _score_row("all", pairs),
        *[_score_row(game, [p for p in pairs if p[0].question.game == game]) for game in games],
        *[_score_row(tag, [p for p in pairs if tag in p[0].question.tags]) for tag in tags],
    ]


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


def format_report(results: ParserResults, settings: Settings, now: datetime) -> str:
    """Scores without and with reranking for all, each game and each tag; each question's top."""
    k = settings.search_results
    pairs = list(zip(results.hybrid, results.reranked, strict=True))
    lines = [
        f"# Retrieval eval: {now:%Y-%m-%d %H:%M}",
        "",
        f"- Parser: {results.parser}",
        *_search_lines(settings),
        f"- Chunks in the eval database: {results.chunk_count}",
        _HIT_NOTE,
        "",
        *_score_table(("Hybrid", "Reranked"), pairs, k),
        "",
        "## Questions",
        "",
        f"| Question | Hybrid first hit | Reranked first hit | Hybrid top {k} (✓ = hit) "
        f"| Reranked top {k} |",
        "| --- | --: | --: | --- | --- |",
    ]
    for hybrid, reranked in pairs:
        lines.append(
            f"| {hybrid.question.id} | {_first_hit(hybrid.hits)} | {_first_hit(reranked.hits)} "
            f"| {_top(hybrid)} | {_top(reranked)} |"
        )
    return "\n".join(lines) + "\n"


def _differences(first: ParserResults, second: ParserResults) -> list[str]:
    rows: list[str] = []
    results = zip(first.hybrid, second.hybrid, first.reranked, second.reranked, strict=True)
    for first_hybrid, second_hybrid, first_reranked, second_reranked in results:
        ranks = [
            _first_hit(result.hits)
            for result in (first_hybrid, second_hybrid, first_reranked, second_reranked)
        ]
        if ranks[0] != ranks[1] or ranks[2] != ranks[3]:
            rows.append(f"| {first_hybrid.question.id} | {' | '.join(ranks)} |")
    return rows


def format_comparison(
    first: ParserResults, second: ParserResults, settings: Settings, now: datetime
) -> str:
    """Two parsers' scores side by side for each search, and the questions whose first hit moved."""
    k = settings.search_results
    names = (first.parser, second.parser)
    differences = _differences(first, second)
    lines = [
        f"# Parser comparison: {now:%Y-%m-%d %H:%M}",
        "",
        f"- Parsers: {first.parser} ({first.chunk_count} chunks), "
        f"{second.parser} ({second.chunk_count} chunks)",
        *_search_lines(settings),
        _HIT_NOTE,
        "",
        "## Hybrid search",
        "",
        *_score_table(names, list(zip(first.hybrid, second.hybrid, strict=True)), k),
        "",
        "## Reranked",
        "",
        *_score_table(names, list(zip(first.reranked, second.reranked, strict=True)), k),
        "",
        "## Questions that differ",
        "",
    ]
    if not differences:
        lines.append("Every question's first hit is at the same rank for both parsers.")
        return "\n".join(lines) + "\n"

    lines += [
        "The rank of each search's first hit (– = none in the top "
        f"{k}); each parser's own report lists its top {k}.",
        "",
        f"| Question | {first.parser} hybrid | {second.parser} hybrid "
        f"| {first.parser} reranked | {second.parser} reranked |",
        "| --- | --: | --: | --: | --: |",
        *differences,
    ]
    return "\n".join(lines) + "\n"
