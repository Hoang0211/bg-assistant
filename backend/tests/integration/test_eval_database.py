import logging
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, inspect, make_url, text

from app.evaluation.database import create_database_if_missing, eval_database_url, migrate


@pytest.fixture
def new_database_url(database_url: str) -> Iterator[str]:
    """A database name on the test server that doesn't exist yet; dropped after the test."""
    url = eval_database_url(database_url, "bg_assistant_eval_test")
    yield url
    server = create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        connection.execute(text('DROP DATABASE IF EXISTS "bg_assistant_eval_test" WITH (FORCE)'))
    server.dispose()


def test_eval_database_url_changes_only_the_database_name() -> None:
    url = eval_database_url(
        "postgresql+psycopg://bg:secret@localhost:5432/bg_assistant", "bg_assistant_eval"
    )

    assert url == "postgresql+psycopg://bg:secret@localhost:5432/bg_assistant_eval"


def test_create_database_if_missing_creates_it_only_once(new_database_url: str) -> None:
    assert create_database_if_missing(new_database_url) is True
    assert create_database_if_missing(new_database_url) is False


def test_migrate_creates_the_tables(new_database_url: str) -> None:
    create_database_if_missing(new_database_url)

    migrate(new_database_url)

    engine = create_engine(new_database_url)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
    engine.dispose()
    assert {"games", "rulebooks", "chunks"} <= tables


def test_migrate_keeps_the_callers_logging(new_database_url: str) -> None:
    create_database_if_missing(new_database_url)
    handlers = list(logging.getLogger().handlers)

    migrate(new_database_url)

    assert logging.getLogger().handlers == handlers
