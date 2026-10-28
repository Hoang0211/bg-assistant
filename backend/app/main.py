from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import games, health
from app.api.error_handlers import register_error_handlers
from app.config import get_settings
from app.db.session import create_db_engine, create_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run startup work before the app serves requests, and cleanup after it stops."""
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    app.state.engine = create_db_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)

    yield
    await app.state.engine.dispose()


app = FastAPI(title="Board Game Assistant API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(games.router, prefix="/api")

register_error_handlers(app)
