from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import database_is_reachable


async def test_database_is_reachable_when_postgres_answers(db_engine: AsyncEngine) -> None:
    assert await database_is_reachable(db_engine)


async def test_database_is_unreachable_when_nothing_listens() -> None:
    engine = create_async_engine("postgresql+psycopg://bg:bg@localhost:1/bg", poolclass=NullPool)
    assert not await database_is_reachable(engine)
    await engine.dispose()


async def test_migrations_enable_the_extensions(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as connection:
        result = await connection.execute(text("SELECT extname FROM pg_extension"))
    assert {"vector", "pg_trgm"} <= set(result.scalars())
