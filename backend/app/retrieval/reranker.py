"""Rerankers score how well each candidate chunk answers a query; higher is better."""

import re
from typing import Protocol


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class FakeReranker:
    """Scores a text by how many of the query's words it has, so tests don't load the model."""

    def score(self, query: str, texts: list[str]) -> list[float]:
        words = set(re.findall(r"\w+", query.lower()))
        return [float(len(words & set(re.findall(r"\w+", text.lower())))) for text in texts]


class BgeReranker:
    """Scores query and text pairs with a BGE cross-encoder, loaded once when created."""

    def __init__(self, model_name: str) -> None:
        # Imported here because it loads PyTorch (about 10 s), and only searching needs it.
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name)

    def score(self, query: str, texts: list[str]) -> list[float]:
        scores: list[float] = self._model.predict([(query, text) for text in texts]).tolist()
        return scores
