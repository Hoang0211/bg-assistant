import pytest

from app.config import get_settings
from app.retrieval.reranker import BgeReranker


@pytest.fixture(scope="module")
def reranker() -> BgeReranker:
    return BgeReranker(get_settings().reranker_model)


def test_bge_reranker_scores_the_relevant_text_higher(reranker: BgeReranker) -> None:
    relevant, unrelated = reranker.score(
        "How many cards do I discard when a 7 is rolled?",
        [
            "Rolling a 7: each player with more than 7 cards discards half of them.",
            "Place the board in the middle of the table.",
        ],
    )

    assert relevant > unrelated
