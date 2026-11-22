from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Chunk, ChunkType, Game, Rulebook
from app.evaluation.answers import (
    AnswerResult,
    JudgeReply,
    ParserAnswers,
    Verdict,
    answer_prompt,
    answer_question,
    check_answer,
    format_answer_details,
    format_answer_report,
    judge_answer,
    judge_prompt,
)
from app.evaluation.questions import ExpectedPlace, GoldenQuestion
from app.ingestion.embedder import FakeEmbedder
from app.llm.base import Completion, StructuredCompletion, Usage
from app.llm.fake import FakeLLMProvider
from app.retrieval.hybrid import SearchResult

SETTINGS = Settings(
    chat_model="chat",
    chat_reasoning_effort="low",
    chat_max_output_tokens=100,
    judge_model="judge",
    judge_reasoning_effort="none",
    judge_max_output_tokens=50,
    search_results=2,
)

QUESTION = GoldenQuestion(
    id="q-1",
    game="Base",
    question="What happens on a 7?",
    expected=[ExpectedPlace(file="Base.pdf", pages=[2])],
    answer="The robber moves.",
    tags=["table"],
)

RESULT = SearchResult(
    chunk_id=1,
    rulebook_id=1,
    game_name="Base",
    is_expansion=False,
    section_path="Robber",
    page_start=2,
    page_end=2,
    content="Robber\n\nOn a 7, move the robber.",
)


def _question(question_id: str, game: str, tags: list[str]) -> GoldenQuestion:
    return QUESTION.model_copy(update={"id": question_id, "game": game, "tags": tags})


def _answer(question: GoldenQuestion, verdict: Verdict) -> AnswerResult:
    return AnswerResult(question, f"{verdict} answer", verdict, f"{verdict} reason", 10, 5)


async def _add_robber_chunk(db_session: AsyncSession) -> FakeEmbedder:
    """A game with one chunk, embedded where the fake embedder puts the question."""
    game = Game(name="Base")
    db_session.add(game)
    await db_session.flush()
    rulebook = Rulebook(
        game_id=game.id,
        filename="Base.pdf",
        storage_path="Base.pdf",
        page_count=3,
        sha256="b" * 64,
    )
    db_session.add(rulebook)
    await db_session.flush()
    embedder = FakeEmbedder()
    db_session.add(
        Chunk(
            rulebook_id=rulebook.id,
            game_id=game.id,
            section_path="Robber",
            chunk_type=ChunkType.SECTION,
            page_start=2,
            page_end=2,
            content="Robber\n\nOn a 7, move the robber.",
            embedding=embedder.embed_query(QUESTION.question),
        )
    )
    await db_session.flush()
    return embedder


def test_answer_prompt_labels_each_excerpt_with_its_game_section_and_pages() -> None:
    expansion = SearchResult(
        chunk_id=2,
        rulebook_id=2,
        game_name="Seafarers",
        is_expansion=True,
        section_path="Ships",
        page_start=4,
        page_end=5,
        content="Ships\n\nBuild ships.",
    )

    assert answer_prompt("What happens on a 7?", [RESULT, expansion]) == (
        "Rulebook excerpts:\n\n"
        "[Base (base game) › Robber, p. 2]\nRobber\n\nOn a 7, move the robber.\n\n"
        "[Seafarers (expansion) › Ships, pp. 4–5]\nShips\n\nBuild ships.\n\n"
        "Question: What happens on a 7?"
    )


async def test_answer_question_asks_the_chat_model_with_the_excerpts() -> None:
    llm = FakeLLMProvider(["The robber moves [p. 2]."])

    completion = await answer_question(llm, SETTINGS, "What happens on a 7?", [RESULT])

    assert completion.text == "The robber moves [p. 2]."
    [call] = llm.calls
    assert (call.model, call.parts, call.max_output_tokens, call.reasoning_effort) == (
        "chat",
        [answer_prompt("What happens on a 7?", [RESULT])],
        100,
        "low",
    )


def test_judge_prompt_shows_the_question_the_reference_and_the_answer() -> None:
    assert judge_prompt(QUESTION, "The robber moves [p. 2].") == (
        "Question: What happens on a 7?\n\n"
        "Reference answer: The robber moves.\n\n"
        "Answer to grade: The robber moves [p. 2]."
    )


async def test_judge_answer_asks_the_judge_model_for_a_structured_reply() -> None:
    reply = JudgeReply(reason="Same fact.", verdict=Verdict.CORRECT)
    llm = FakeLLMProvider([reply])

    completion = await judge_answer(llm, SETTINGS, QUESTION, "The robber moves [p. 2].")

    assert completion.value == reply
    [call] = llm.calls
    assert (call.model, call.parts, call.schema, call.max_output_tokens, call.reasoning_effort) == (
        "judge",
        [judge_prompt(QUESTION, "The robber moves [p. 2].")],
        JudgeReply,
        50,
        "none",
    )


async def test_check_answer_answers_from_the_search_results_and_judges_the_answer(
    db_session: AsyncSession,
) -> None:
    embedder = await _add_robber_chunk(db_session)
    reply = JudgeReply(reason="Same fact.", verdict=Verdict.CORRECT)
    llm = FakeLLMProvider(
        [
            Completion(" The robber moves [p. 2]. ", True, Usage(100, 0, 20, 5)),
            StructuredCompletion(reply, True, Usage(40, 0, 3, 0)),
        ]
    )

    result = await check_answer(db_session, embedder, llm, SETTINGS, QUESTION)

    assert result == AnswerResult(
        question=QUESTION,
        answer="The robber moves [p. 2].",
        verdict=Verdict.CORRECT,
        reason="Same fact.",
        input_tokens=140,
        output_tokens=23,
    )
    answer_call, judge_call = llm.calls
    assert "[Base (base game) › Robber, p. 2]\nRobber\n\nOn a 7, move the robber." in str(
        answer_call.parts[0]
    )
    assert judge_call.parts == [judge_prompt(QUESTION, "The robber moves [p. 2].")]


async def test_check_answer_counts_a_missing_verdict_as_wrong(db_session: AsyncSession) -> None:
    embedder = await _add_robber_chunk(db_session)
    llm = FakeLLMProvider(
        ["The robber moves [p. 2].", StructuredCompletion(None, False, Usage(40, 0, 50, 50))]
    )

    result = await check_answer(db_session, embedder, llm, SETTINGS, QUESTION)

    assert (result.verdict, result.reason) == (
        Verdict.WRONG,
        "no verdict: the judge's reply was cut off or refused",
    )


def test_format_answer_report_counts_each_parsers_verdicts_and_lists_each_question() -> None:
    base = _question("q-1", "Base", ["table"])
    expansion = _question("q-2", "Expansion", [])
    docling = ParserAnswers(
        "docling", [_answer(base, Verdict.PARTIAL), _answer(expansion, Verdict.WRONG)]
    )
    llm = ParserAnswers("llm", [_answer(base, Verdict.CORRECT), _answer(expansion, Verdict.WRONG)])

    report = format_answer_report(docling, llm, SETTINGS, datetime(2026, 11, 21, 14, 5))

    assert report == (
        "# Answer check: 2026-11-21 14:05\n"
        "\n"
        "- Each question's top 2 chunks from hybrid search go to chat, which answers from them"
        " only; judge grades the answer against the golden answer.\n"
        "- Correct: the golden answer's facts, none contradicted. Partial: only some of them, or"
        ' a hedge. Wrong: a contradiction, the main fact missing, or "not covered".\n'
        "- The answers quote the rulebooks, so they're kept out of this report.\n"
        "\n"
        "| Questions | Count | docling correct | docling partial | docling wrong"
        " | llm correct | llm partial | llm wrong |\n"
        "| --- | --: | --: | --: | --: | --: | --: | --: |\n"
        "| all | 2 | 0 | 1 | 1 | 1 | 0 | 1 |\n"
        "| Base | 1 | 0 | 1 | 0 | 1 | 0 | 0 |\n"
        "| Expansion | 1 | 0 | 0 | 1 | 0 | 0 | 1 |\n"
        "| table | 1 | 0 | 1 | 0 | 1 | 0 | 0 |\n"
        "\n"
        "## Questions\n"
        "\n"
        "| Question | docling | llm | Differ |\n"
        "| --- | --- | --- | --- |\n"
        "| q-1 | partial | correct | ≠ |\n"
        "| q-2 | wrong | wrong |  |\n"
    )


def test_format_answer_details_shows_each_questions_answers_and_verdicts() -> None:
    docling = ParserAnswers("docling", [_answer(QUESTION, Verdict.WRONG)])
    llm = ParserAnswers("llm", [_answer(QUESTION, Verdict.CORRECT)])

    details = format_answer_details(docling, llm, datetime(2026, 11, 21, 14, 5))

    assert details == (
        "# Answer check details: 2026-11-21 14:05\n"
        "\n"
        "## q-1 (verdicts differ)\n"
        "\n"
        "**Question:** What happens on a 7?\n"
        "\n"
        "**Golden answer:** The robber moves.\n"
        "\n"
        "**docling: wrong.** wrong reason\n"
        "\n"
        "wrong answer\n"
        "\n"
        "**llm: correct.** correct reason\n"
        "\n"
        "correct answer\n"
    )
