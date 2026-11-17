from pathlib import Path

from app.evaluation.library import LibraryExpansion, LibraryGame, read_library
from app.evaluation.questions import ExpectedPlace, GoldenQuestion, read_questions


def test_read_questions_reads_each_question(tmp_path: Path) -> None:
    path = tmp_path / "questions.json"
    path.write_text(
        '{"about": "ignored", "tags": {}, "questions": [{"id": "q-1", "game": "Base",'
        ' "question": "How?", "expected": [{"file": "base.pdf", "pages": [3]}],'
        ' "answer": "Like this.", "tags": ["table"]}]}',
        encoding="utf-8",
    )

    assert read_questions(path) == [
        GoldenQuestion(
            id="q-1",
            game="Base",
            question="How?",
            expected=[ExpectedPlace(file="base.pdf", pages=[3])],
            answer="Like this.",
            tags=["table"],
        )
    ]


def test_golden_questions_match_the_library() -> None:
    questions = read_questions(Path("eval/golden_questions.json"))
    library = read_library(Path("eval/library.json"))
    expansions = [expansion for game in library.games for expansion in game.expansions]
    games: list[LibraryGame | LibraryExpansion] = [*library.games, *expansions]
    names = [game.name for game in games]
    files = {rulebook.file for game in games for rulebook in game.rulebooks}

    assert len(set(names)) == len(names)  # the eval finds each question's game by its name
    assert {question.game for question in questions} <= set(names)
    assert {place.file for question in questions for place in question.expected} <= files
