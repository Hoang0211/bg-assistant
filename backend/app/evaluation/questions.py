"""The golden questions: what the retrieval eval asks, and where each answer is printed."""

from pathlib import Path

from pydantic import BaseModel


class ExpectedPlace(BaseModel):
    file: str  # a rulebook's file name in the eval library
    pages: list[int]  # PDF page numbers, from 1


class GoldenQuestion(BaseModel):
    id: str
    game: str  # the game the question is asked about; its whole family is searched
    question: str
    expected: list[ExpectedPlace]  # any of them counts
    answer: str
    tags: list[str]


class GoldenQuestions(BaseModel):
    questions: list[GoldenQuestion]


def read_questions(path: Path) -> list[GoldenQuestion]:
    return GoldenQuestions.model_validate_json(path.read_text(encoding="utf-8")).questions
