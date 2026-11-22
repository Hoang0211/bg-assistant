"""The answer check: answer each golden question from its search results, then grade the answer."""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.evaluation.questions import GoldenQuestion
from app.evaluation.retrieval import family_game_ids
from app.ingestion.embedder import Embedder
from app.llm.base import Completion, LLMProvider, StructuredCompletion
from app.retrieval.hybrid import SearchResult, hybrid_search

logger = logging.getLogger(__name__)


class Verdict(StrEnum):
    CORRECT = "correct"
    PARTIAL = "partial"
    WRONG = "wrong"


@dataclass(frozen=True)
class AnswerResult:
    question: GoldenQuestion
    answer: str
    verdict: Verdict
    reason: str  # the judge's, or why there's no verdict
    input_tokens: int  # both calls together
    output_tokens: int


# Static and sent first, so OpenAI can cache it across questions.
_ANSWER_INSTRUCTIONS = """\
You answer questions about board game rules using only the rulebook excerpts given with the
question. Each excerpt starts with its game, section and pages in square brackets.

- Answer directly, in one to three sentences.
- Cite the page of each fact you use, as [p. 12].
- If the excerpts don't answer the question, reply only "The excerpts don't cover this." Never
answer from general knowledge."""


def _pages(result: SearchResult) -> str:
    if result.page_start == result.page_end:
        return f"p. {result.page_start}"
    return f"pp. {result.page_start}–{result.page_end}"


def _excerpt(result: SearchResult) -> str:
    kind = "expansion" if result.is_expansion else "base game"
    label = f"{result.game_name} ({kind}) › {result.section_path}, {_pages(result)}"
    return f"[{label}]\n{result.content}"


def answer_prompt(question: str, results: list[SearchResult]) -> str:
    excerpts = "\n\n".join(_excerpt(result) for result in results)
    return f"Rulebook excerpts:\n\n{excerpts}\n\nQuestion: {question}"


async def answer_question(
    llm: LLMProvider, settings: Settings, question: str, results: list[SearchResult]
) -> Completion:
    """The chat model's answer to the question, from the search results only."""
    return await llm.complete(
        settings.chat_model,
        _ANSWER_INSTRUCTIONS,
        [answer_prompt(question, results)],
        settings.chat_max_output_tokens,
        settings.chat_reasoning_effort,
    )


class JudgeReply(BaseModel):
    """The judge's reply. The reason comes first, so the model decides after explaining."""

    reason: str
    verdict: Verdict


_JUDGE_INSTRUCTIONS = """\
You grade an answer to a board game rules question against the reference answer, which is
correct. Give your reason in one or two sentences, then the verdict:

- correct: the answer states the reference answer's facts that the question asks for, and
contradicts none of them.
- partial: it states only some of those facts, or hedges between the right answer and a wrong
one.
- wrong: it contradicts the reference answer, misses its main fact, or says the rulebook
doesn't cover the question.

When grading:
- Don't penalise different wording, page citations, or extra detail that is correct.
- Don't penalise leaving out details of the reference answer that the question didn't ask about.
- Penalise any statement that contradicts the reference answer, even next to a correct one.
- Penalise applying a rule more broadly than the reference answer does, such as stating a worked
example's result as the general rule, or an expansion's or a card's rule as a rule of the whole
game."""


def judge_prompt(question: GoldenQuestion, answer: str) -> str:
    return (
        f"Question: {question.question}\n\n"
        f"Reference answer: {question.answer}\n\n"
        f"Answer to grade: {answer}"
    )


async def judge_answer(
    llm: LLMProvider, settings: Settings, question: GoldenQuestion, answer: str
) -> StructuredCompletion[JudgeReply]:
    """The judge model's reason and verdict, comparing the answer with the golden answer."""
    return await llm.complete_structured(
        settings.judge_model,
        _JUDGE_INSTRUCTIONS,
        [judge_prompt(question, answer)],
        JudgeReply,
        settings.judge_max_output_tokens,
        settings.judge_reasoning_effort,
    )


async def check_answer(
    session: AsyncSession,
    embedder: Embedder,
    llm: LLMProvider,
    settings: Settings,
    question: GoldenQuestion,
) -> AnswerResult:
    """Search the question's game family with hybrid search, answer from the top, judge it."""
    game_ids = await family_game_ids(session, question.game)
    results = await hybrid_search(
        session, embedder, question.question, game_ids, limit=settings.search_results
    )
    answer = await answer_question(llm, settings, question.question, results)
    if not answer.complete:
        logger.warning("%s's answer was cut off at the output-token cap", question.id)
    judged = await judge_answer(llm, settings, question, answer.text.strip())
    if judged.value is None:
        logger.warning("%s's verdict was cut off or refused", question.id)
        verdict, reason = Verdict.WRONG, "no verdict: the judge's reply was cut off or refused"
    else:
        verdict, reason = judged.value.verdict, judged.value.reason
    return AnswerResult(
        question=question,
        answer=answer.text.strip(),
        verdict=verdict,
        reason=reason,
        input_tokens=answer.usage.input_tokens + judged.usage.input_tokens,
        output_tokens=answer.usage.output_tokens + judged.usage.output_tokens,
    )


def _count_row(label: str, results: list[AnswerResult]) -> str:
    counts = " | ".join(
        str(sum(result.verdict == verdict for result in results)) for verdict in Verdict
    )
    return f"| {label} | {len(results)} | {counts} |"


def format_answer_report(results: list[AnswerResult], settings: Settings, now: datetime) -> str:
    """The verdict counts for all, each game and each tag, then each question's verdict."""
    games = list(dict.fromkeys(result.question.game for result in results))  # in question order
    tags = sorted({tag for result in results for tag in result.question.tags})
    lines = [
        f"# Answer check: {now:%Y-%m-%d %H:%M}",
        "",
        f"- Each question's top {settings.search_results} chunks from hybrid search go to"
        f" {settings.chat_model}, which answers from them only; {settings.judge_model} grades"
        " the answer against the golden answer.",
        "- Correct: the golden answer's facts, none contradicted. Partial: only some of them, or"
        ' a hedge. Wrong: a contradiction, the main fact missing, or "not covered".',
        "- The answers quote the rulebooks, so they're kept out of this report.",
        "",
        "| Questions | Count | Correct | Partial | Wrong |",
        "| --- | --: | --: | --: | --: |",
        _count_row("all", results),
        *[_count_row(game, [r for r in results if r.question.game == game]) for game in games],
        *[_count_row(tag, [r for r in results if tag in r.question.tags]) for tag in tags],
        "",
        "## Questions",
        "",
        "| Question | Verdict |",
        "| --- | --- |",
        *[f"| {result.question.id} | {result.verdict} |" for result in results],
    ]
    return "\n".join(lines) + "\n"


def format_answer_details(results: list[AnswerResult], now: datetime) -> str:
    """Every question's answer, verdict and reason in full, for reading by hand; not committed."""
    lines = [f"# Answer check details: {now:%Y-%m-%d %H:%M}"]
    for result in results:
        lines += [
            "",
            f"## {result.question.id}",
            "",
            f"**Question:** {result.question.question}",
            "",
            f"**Golden answer:** {result.question.answer}",
            "",
            f"**{result.verdict}.** {result.reason}",
            "",
            result.answer,
        ]
    return "\n".join(lines) + "\n"
