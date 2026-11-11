import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from functools import partial

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import games, health, rulebooks
from app.api.error_handlers import register_error_handlers
from app.config import get_settings
from app.db.session import create_db_engine, create_sessionmaker
from app.ingestion.embedder import BgeEmbedder
from app.ingestion.jobs import IngestionWorker
from app.ingestion.parse_process import parse_in_process
from app.log_setup import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run startup work before the app serves requests, and cleanup after it stops."""
    configure_logging()
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    app.state.engine = create_db_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)

    worker = IngestionWorker(
        app.state.sessionmaker,
        settings.upload_dir,
        partial(parse_in_process, attempts=settings.parse_attempts),
        partial(BgeEmbedder, settings.embedding_model),
    )
    app.state.ingestion_worker = worker
    worker_task: asyncio.Task[None] | None = None
    if settings.run_ingestion_worker:
        try:
            await worker.requeue_unfinished()
        except Exception:
            # The app still starts without a database; the health check reports it.
            logger.exception("could not queue the unfinished rulebooks")
        worker_task = asyncio.create_task(worker.run())

    yield

    if worker_task is not None:
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task
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
app.include_router(rulebooks.router, prefix="/api")

register_error_handlers(app)
