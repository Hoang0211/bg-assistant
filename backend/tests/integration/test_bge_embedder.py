import math

import pytest

from app.config import get_settings
from app.db.models import EMBEDDING_DIMENSION
from app.ingestion.embedder import QUERY_PREFIX, BgeEmbedder


@pytest.fixture(scope="module")
def embedder() -> BgeEmbedder:
    return BgeEmbedder(get_settings().embedding_model)


def test_bge_embedder_counts_tokens_without_special_tokens(embedder: BgeEmbedder) -> None:
    assert embedder.count_tokens("Roll a 7.") == 4


def test_bge_embedder_adds_the_query_prefix_only_to_queries(embedder: BgeEmbedder) -> None:
    query = embedder.embed_query("Roll a 7.")
    prefixed, plain = embedder.embed_documents([QUERY_PREFIX + "Roll a 7.", "Roll a 7."])

    assert query == pytest.approx(prefixed, abs=1e-6)
    assert query != pytest.approx(plain, abs=1e-6)


def test_bge_embedder_returns_unit_vectors_of_the_embedding_dimension(
    embedder: BgeEmbedder,
) -> None:
    [vector] = embedder.embed_documents(["Roll a 7."])

    assert len(vector) == EMBEDDING_DIMENSION
    assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1)
