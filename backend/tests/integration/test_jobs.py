import asyncio
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Game, Rulebook, RulebookStatus
from app.ingestion.elements import Element, ElementKind
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.jobs import IngestionWorker
from tests.helpers import make_pdf

ELEMENTS = [
    Element(ElementKind.HEADING, "Setup", 1),
    Element(ElementKind.PARAGRAPH, "Roll the dice.", 1),
]


async def _add_rulebook(
    db_session: AsyncSession, tmp_path: Path, name: str, status: RulebookStatus
) -> Rulebook:
    (tmp_path / name).write_bytes(make_pdf(1))
    game = Game(name="Catan")
    db_session.add(game)
    await db_session.flush()
    rulebook = Rulebook(
        game_id=game.id,
        filename=name,
        storage_path=name,
        page_count=1,
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        status=status,
    )
    db_session.add(rulebook)
    await db_session.commit()
    return rulebook


async def _run_until_idle(worker: IngestionWorker) -> None:
    task = asyncio.create_task(worker.run())
    async with asyncio.timeout(30):
        await worker.wait_until_idle()
    task.cancel()


async def test_worker_requeues_only_unfinished_rulebooks(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    for name, status in [
        ("uploaded.pdf", RulebookStatus.UPLOADED),
        ("processing.pdf", RulebookStatus.PROCESSING),
        ("ready.pdf", RulebookStatus.READY),
        ("failed.pdf", RulebookStatus.FAILED),
    ]:
        await _add_rulebook(db_session, tmp_path, name, status)
    parsed: list[str] = []

    def parse(path: Path) -> list[Element]:
        parsed.append(path.name)
        return ELEMENTS

    worker = IngestionWorker(sessionmaker, tmp_path, parse, FakeEmbedder)
    await worker.requeue_unfinished()
    await _run_until_idle(worker)

    assert parsed == ["uploaded.pdf", "processing.pdf"]


async def test_worker_creates_the_embedder_once(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    first = await _add_rulebook(db_session, tmp_path, "first.pdf", RulebookStatus.UPLOADED)
    second = await _add_rulebook(db_session, tmp_path, "second.pdf", RulebookStatus.UPLOADED)
    created: list[FakeEmbedder] = []

    def make_embedder() -> FakeEmbedder:
        embedder = FakeEmbedder()
        created.append(embedder)
        return embedder

    worker = IngestionWorker(sessionmaker, tmp_path, lambda path: ELEMENTS, make_embedder)
    worker.enqueue(first.id)
    worker.enqueue(second.id)
    await _run_until_idle(worker)

    statuses = (await db_session.scalars(select(Rulebook.status).order_by(Rulebook.id))).all()
    assert statuses == [RulebookStatus.READY, RulebookStatus.READY]
    assert len(created) == 1


async def test_worker_keeps_running_after_a_job_fails(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    first = await _add_rulebook(db_session, tmp_path, "first.pdf", RulebookStatus.UPLOADED)
    second = await _add_rulebook(db_session, tmp_path, "second.pdf", RulebookStatus.UPLOADED)
    failures = [OSError("model files not found")]

    def make_embedder() -> FakeEmbedder:
        if failures:
            raise failures.pop()
        return FakeEmbedder()

    worker = IngestionWorker(sessionmaker, tmp_path, lambda path: ELEMENTS, make_embedder)
    worker.enqueue(first.id)
    worker.enqueue(second.id)
    await _run_until_idle(worker)

    rows = await db_session.execute(select(Rulebook.status, Rulebook.error).order_by(Rulebook.id))
    assert rows.all() == [
        (RulebookStatus.FAILED, "model files not found"),
        (RulebookStatus.READY, None),
    ]
