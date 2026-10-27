from collections.abc import AsyncIterator, Iterator

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from alembic import command


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Start a throwaway pgvector Postgres for the test run and apply every migration to it."""
    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        alembic_config = Config("alembic.ini")
        alembic_config.set_main_option("sqlalchemy.url", url)
        command.upgrade(alembic_config, "head")
        yield url


@pytest.fixture
async def db_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """An async engine for the test database, created fresh for each test."""
    # NullPool: each test runs on its own event loop, so connections must never be reused.
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()
