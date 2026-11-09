import math
import random
from typing import Protocol

from sentence_transformers import SentenceTransformer

from app.db.models import EMBEDDING_DIMENSION

# BGE expects this before a search query, but not before the passages being searched.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    def count_tokens(self, text: str) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Counts words and returns a fixed unit vector per text, so tests don't load the model."""

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        generator = random.Random(text)
        vector = [generator.gauss(0, 1) for _ in range(EMBEDDING_DIMENSION)]
        length = math.sqrt(sum(value * value for value in vector))
        return [value / length for value in vector]


class BgeEmbedder:
    """Embeds text with a BGE model, loaded once when created."""

    def __init__(self, model_name: str) -> None:
        self._model = SentenceTransformer(model_name)

    def count_tokens(self, text: str) -> int:
        # verbose=False: counting a long section before it's split would warn that it's over 512.
        tokens = self._model.tokenizer(text, add_special_tokens=False, verbose=False)
        return len(tokens["input_ids"])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = self._model.encode(texts, normalize_embeddings=True).tolist()
        return vectors

    def embed_query(self, text: str) -> list[float]:
        vector: list[float] = self._model.encode(
            QUERY_PREFIX + text, normalize_embeddings=True
        ).tolist()
        return vector
