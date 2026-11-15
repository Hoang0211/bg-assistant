"""Retrieval metrics over one question's top results, each marked as a hit or not."""

import math
from dataclasses import dataclass

from app.evaluation.questions import ExpectedPlace


@dataclass(frozen=True)
class Place:
    """Where a chunk is printed: its rulebook file and page range."""

    file: str
    page_start: int
    page_end: int


def is_hit(place: Place, expected: list[ExpectedPlace]) -> bool:
    """Whether the chunk is from an expected file and covers one of that file's expected pages."""
    return any(
        entry.file == place.file
        and any(place.page_start <= page <= place.page_end for page in entry.pages)
        for entry in expected
    )


def recall(hits: list[bool]) -> float:
    """1 if any result is a hit, else 0: the question's answer was found or it wasn't."""
    return 1.0 if any(hits) else 0.0


def reciprocal_rank(hits: list[bool]) -> float:
    """1 / the first hit's rank, or 0 without a hit."""
    for rank, hit in enumerate(hits, start=1):
        if hit:
            return 1 / rank
    return 0.0


def ndcg(hits: list[bool], relevant_count: int, k: int) -> float:
    """How close the hits are to the top, against the best possible order of k results.

    relevant_count is how many chunks in the searched games are hits; the best order puts
    min(k, relevant_count) of them first.
    """
    dcg = sum(1 / math.log2(rank + 1) for rank, hit in enumerate(hits, start=1) if hit)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, relevant_count) + 1))
    return dcg / ideal if ideal else 0.0
