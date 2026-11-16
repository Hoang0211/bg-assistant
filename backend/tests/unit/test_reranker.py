from app.retrieval.reranker import FakeReranker


def test_fake_reranker_counts_the_query_words_each_text_contains() -> None:
    texts = ["The youngest player goes first.", "Roll the dice.", "WHO?"]

    assert FakeReranker().score("Who goes first?", texts) == [2.0, 0.0, 1.0]
