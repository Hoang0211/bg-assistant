import pytest
from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_migrations_match_the_models(database_url: str) -> None:
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.check(alembic_config)


def test_migrations_read_a_percent_escaped_url_from_the_settings(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # %74 is "t": the test server's password "test", written the way a password with a special
    # character has to be (the @ in "p@ss" as %40).
    escaped = database_url.replace(":test@", ":%74est@")
    assert escaped != database_url
    monkeypatch.setenv("DATABASE_URL", escaped)
    get_settings.cache_clear()
    try:
        # With no URL in its config, env.py takes the settings' DATABASE_URL, as just migrate does.
        # The database is already at head, so this only connects and checks.
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        get_settings.cache_clear()
