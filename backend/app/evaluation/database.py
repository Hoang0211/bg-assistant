"""The eval's own database, next to the dev database on the same Postgres server."""

from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from alembic import command


def eval_database_url(database_url: str, name: str) -> str:
    """The same server and credentials as database_url, with another database name."""
    return make_url(database_url).set(database=name).render_as_string(hide_password=False)


def create_database_if_missing(url: str) -> bool:
    """Create the URL's database unless it exists; return whether it was created."""
    target = make_url(url)
    # CREATE DATABASE can't run inside a transaction, so this connects to the server's own
    # postgres database in autocommit mode.
    engine = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            )
            if exists:
                return False
            connection.execute(text(f'CREATE DATABASE "{target.database}"'))
            return True
    finally:
        engine.dispose()


def migrate(url: str) -> None:
    """Apply every Alembic migration to the URL's database."""
    config = Config("alembic.ini")
    # Alembic's config reads % as the start of a variable, and a password's special characters
    # are written as %-escapes in a URL (@ as %40), so each % is doubled.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    # The caller has set up logging already; env.py would otherwise replace it.
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
