"""Download every model the app loads, once per machine: python -m app.ingestion.download_models."""

from app.config import get_settings
from app.ingestion.embedder import BgeEmbedder
from app.retrieval.reranker import BgeReranker


def main() -> None:
    settings = get_settings()
    BgeEmbedder(settings.embedding_model)
    BgeReranker(settings.reranker_model)


if __name__ == "__main__":
    main()
