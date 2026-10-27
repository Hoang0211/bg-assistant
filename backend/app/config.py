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

    # Lists frontend origins allowed to call API from browser
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Return the settings, created on the first call and reused afterwards."""
    return Settings()
