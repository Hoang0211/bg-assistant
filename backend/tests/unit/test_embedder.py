import math

import pytest

from app.db.models import EMBEDDING_DIMENSION
from app.ingestion.embedder import FakeEmbedder


def test_fake_embedder_returns_the_same_vector_for_the_same_text() -> None:
    embedder = FakeEmbedder()
    first, second = embedder.embed_documents(["Roll a 7.", "Roll a 7."])

    assert first == second
    assert embedder.embed_query("Roll a 7.") == first


def test_fake_embedder_returns_unit_vectors_of_the_embedding_dimension() -> None:
    vector = FakeEmbedder().embed_query("Roll a 7.")

    assert len(vector) == EMBEDDING_DIMENSION
    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1)


def test_fake_embedder_returns_different_vectors_for_different_texts() -> None:
    first, second = FakeEmbedder().embed_documents(["Roll a 7.", "Roll an 8."])

    assert first != second


def test_fake_embedder_counts_words_as_tokens() -> None:
    assert FakeEmbedder().count_tokens("Roll a 7 and\n\ndiscard half.") == 6
