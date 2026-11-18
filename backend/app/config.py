from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm.base import ReasoningEffort


class Settings(BaseSettings):
    """Application settings.

    Values come from environment variables first, then `backend/.env`, then the defaults below.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://bg:bg@localhost:5432/bg_assistant"

    # Relative paths are resolved from the directory the app runs in (backend/).
    upload_dir: Path = Path("data/uploads")

    # The eval's own database, on the same server as database_url; just eval-ingest builds it.
    eval_database_name: str = "bg_assistant_eval"

    # The eval's questions and library, and the rulebook PDFs it's built from.
    eval_dir: Path = Path("eval")
    eval_rulebooks_dir: Path = Path("data/rulebooks")

    # Largest rulebook PDF accepted, in MB.
    max_upload_mb: int = 50

    # Pages with fewer characters in their text layer are parsed with OCR.
    ocr_min_page_chars: int = 100

    # Times the parse is tried in its own process before the rulebook is marked as failed.
    parse_attempts: int = 3

    # A parse that runs longer than this is stopped and not tried again.
    parse_timeout_seconds: int = 600

    # Off in tests, so starting the app there doesn't ingest rulebooks from the dev database.
    run_ingestion_worker: bool = True

    # Sections with fewer tokens are merged into a neighbouring section.
    chunk_min_tokens: int = 80

    # A section over the max is split into chunks of about the target size.
    chunk_target_tokens: int = 350
    chunk_max_tokens: int = 450

    # A chunk's last element is repeated in the next chunk if it's at most this long.
    chunk_overlap_tokens: int = 50

    # Embedding model from Hugging Face. Changing it means reindexing, and a migration if its
    # vector size differs.
    embedding_model: str = "BAAI/bge-base-en-v1.5"

    # Hybrid search: candidates kept from vector and from full-text search, Reciprocal Rank
    # Fusion's k, and how many fused chunks go on to the reranker.
    vector_candidates: int = 30
    full_text_candidates: int = 30
    rrf_k: int = 60
    fused_candidates: int = 20

    # Cross-encoder from Hugging Face that reranks the fused chunks.
    reranker_model: str = "BAAI/bge-reranker-base"

    # Chunks a search returns: the ones sent to the LLM, and the ones the eval scores.
    search_results: int = 5

    # "openai", or "fake" for scripted replies with no API key (tests always use it).
    llm_provider: Literal["openai", "fake"] = "openai"
    openai_api_key: SecretStr = SecretStr("")  # set in .env only

    # Seconds before a request to the LLM is given up and retried.
    llm_timeout_seconds: float = 120

    # The vision model that writes each rulebook page as Markdown, and its reasoning effort.
    # The output cap is a spending guard: the densest page tried needed about 1,900 tokens.
    parser_model: str = "gpt-6.1-terra"
    parser_reasoning_effort: ReasoningEffort = "low"
    parser_max_output_tokens: int = 4000

    # Each page is rendered so its longer side is this many pixels: enough for the densest page
    # tried, at about 3,300 input tokens a page.
    parser_image_px: int = 2048

    # Lists frontend origins allowed to call API from browser
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return the settings, created on the first call and reused afterwards."""
    return Settings()
