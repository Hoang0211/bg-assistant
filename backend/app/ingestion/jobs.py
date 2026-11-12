import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Rulebook, RulebookStatus
from app.ingestion.elements import Element
from app.ingestion.embedder import Embedder
from app.ingestion.pipeline import ingest_rulebook, mark_failed

logger = logging.getLogger(__name__)


class IngestionWorker:
    """Ingests queued rulebooks one at a time, in the background."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        upload_dir: Path,
        parse: Callable[[Path], list[Element]],
        make_embedder: Callable[[], Embedder],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._upload_dir = upload_dir
        self._parse = parse
        self._make_embedder = make_embedder
        # Created on the first job, so starting the app doesn't wait for the model to load.
        self._embedder: Embedder | None = None
        self._queue: asyncio.Queue[int] = asyncio.Queue()

    def enqueue(self, rulebook_id: int) -> None:
        self._queue.put_nowait(rulebook_id)

    async def requeue_unfinished(self) -> None:
        """Queue the rulebooks left uploaded or processing when the backend last stopped."""
        async with self._sessionmaker() as session:
            ids = await session.scalars(
                select(Rulebook.id)
                .where(Rulebook.status.in_([RulebookStatus.UPLOADED, RulebookStatus.PROCESSING]))
                .order_by(Rulebook.id)
            )
            for rulebook_id in ids:
                self.enqueue(rulebook_id)

    async def run(self) -> None:
        """Ingest queued rulebooks until cancelled; a job that fails doesn't stop the worker."""
        while True:
            rulebook_id = await self._queue.get()
            try:
                await self._ingest(rulebook_id)
            except Exception:
                logger.exception("ingestion job for rulebook %d stopped", rulebook_id)
            finally:
                self._queue.task_done()

    async def wait_until_idle(self) -> None:
        """Wait until every queued rulebook has been ingested."""
        await self._queue.join()

    async def _ingest(self, rulebook_id: int) -> None:
        async with self._sessionmaker() as session:
            if self._embedder is None:
                logger.info("loading the embedding model")
                try:
                    self._embedder = await asyncio.to_thread(self._make_embedder)
                except Exception as error:
                    await mark_failed(session, rulebook_id, error)
                    raise
            await ingest_rulebook(
                session, rulebook_id, self._upload_dir, self._parse, self._embedder
            )
