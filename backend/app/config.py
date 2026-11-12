from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Values come from environment variables first, then `backend/.env`, then the defaults below.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://bg:bg@localhost:5432/bg_assistant"

    # Relative paths are resolved from the directory the app runs in (backend/).
    upload_dir: Path = Path("data/uploads")

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

    # Lists frontend origins allowed to call API from browser
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return the settings, created on the first call and reused afterwards."""
    return Settings()
