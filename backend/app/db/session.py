import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_db_engine(settings: Settings) -> AsyncEngine:
    """Create the async database engine (a connection pool) from the settings."""
    return create_async_engine(settings.database_url, pool_pre_ping=True)


async def database_is_reachable(engine: AsyncEngine) -> bool:
    """Return whether the database answers a trivial query within 2 seconds."""
    try:
        async with asyncio.timeout(2), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (TimeoutError, SQLAlchemyError):
        return False
    return True


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the factory that opens a new session for each request."""
    return async_sessionmaker(engine, expire_on_commit=False)
