"""Answers and grades one question with the real models, so it runs only with just test-live."""

import pytest
from openai import AsyncOpenAI

from app.config import get_settings
from app.evaluation.answers import Verdict, answer_question, judge_answer
from app.evaluation.questions import GoldenQuestion
from app.llm.openai import OpenAIProvider
from app.retrieval.hybrid import SearchResult

pytestmark = pytest.mark.live


async def test_answer_question_and_judge_answer_grade_a_supported_answer_correct() -> None:
    settings = get_settings()
    llm = OpenAIProvider(
        AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), max_retries=0)
    )
    question = GoldenQuestion(
        id="q-1",
        game="Base",
        question="How many cards does each player draw at the start?",
        expected=[],
        answer="5 cards.",
        tags=[],
    )
    excerpt = SearchResult(
        chunk_id=1,
        rulebook_id=1,
        game_name="Base",
        is_expansion=False,
        section_path="Setup",
        page_start=3,
        page_end=3,
        content="Setup\n\nShuffle the deck. Each player draws 5 cards and keeps them hidden.",
    )

    answer = await answer_question(llm, settings, question.question, [excerpt])
    judged = await judge_answer(llm, settings, question, answer.text)

    assert answer.complete and judged.complete
    assert "5" in answer.text
    assert judged.value is not None
    assert judged.value.verdict == Verdict.CORRECT
