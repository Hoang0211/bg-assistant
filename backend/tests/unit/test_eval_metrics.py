import math

import pytest

from app.evaluation.metrics import Place, is_hit, ndcg, recall, reciprocal_rank
from app.evaluation.questions import ExpectedPlace

EXPECTED = [ExpectedPlace(file="base.pdf", pages=[3]), ExpectedPlace(file="exp.pdf", pages=[1, 7])]


@pytest.mark.parametrize(
    "place",
    [Place("base.pdf", 3, 3), Place("base.pdf", 2, 4), Place("exp.pdf", 7, 8)],
)
def test_is_hit_accepts_a_chunk_covering_an_expected_page(place: Place) -> None:
    assert is_hit(place, EXPECTED)


@pytest.mark.parametrize(
    "place",
    [Place("base.pdf", 4, 5), Place("base.pdf", 1, 2), Place("other.pdf", 3, 3)],
)
def test_is_hit_rejects_a_chunk_off_the_expected_pages_or_files(place: Place) -> None:
    assert not is_hit(place, EXPECTED)


def test_recall_is_one_when_any_result_is_a_hit() -> None:
    assert recall([False, False, True]) == 1.0


def test_recall_is_zero_without_a_hit() -> None:
    assert recall([False, False, False]) == 0.0


def test_reciprocal_rank_is_one_over_the_first_hits_rank() -> None:
    assert reciprocal_rank([False, True, True]) == 0.5


def test_reciprocal_rank_is_zero_without_a_hit() -> None:
    assert reciprocal_rank([False, False, False]) == 0.0


def test_ndcg_is_one_when_the_hits_fill_the_top() -> None:
    assert ndcg([True, True, False, False, False], relevant_count=2, k=5) == 1.0


def test_ndcg_is_lower_when_a_hit_ranks_lower() -> None:
    assert ndcg([False, True, False, False, False], relevant_count=1, k=5) == pytest.approx(
        1 / math.log2(3)
    )


def test_ndcg_compares_with_at_most_k_relevant_chunks() -> None:
    assert ndcg([True, True, True], relevant_count=10, k=3) == 1.0


def test_ndcg_is_zero_without_relevant_chunks() -> None:
    assert ndcg([False, False, False], relevant_count=0, k=3) == 0.0
