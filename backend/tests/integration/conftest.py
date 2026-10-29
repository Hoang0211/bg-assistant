from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.api.deps import get_session, get_upload_dir
from app.main import app


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


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose changes are rolled back after the test, even if the code commits."""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def api_client(client: AsyncClient, db_session: AsyncSession, tmp_path: Path) -> AsyncClient:
    """The HTTP client, with every request using the test's rolled-back session."""
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_upload_dir] = lambda: tmp_path
    return client
