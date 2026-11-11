import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli import _parser, reindex
from app.db.models import Chunk, Game, Rulebook, RulebookStatus
from app.ingestion.elements import Element, ElementKind
from app.ingestion.embedder import FakeEmbedder
from tests.helpers import make_pdf

ELEMENTS = [Element(ElementKind.HEADING, "Setup", 1), Element(ElementKind.PARAGRAPH, "Roll.", 1)]


async def _add_rulebook(
    db_session: AsyncSession, tmp_path: Path, game: str, name: str, status: RulebookStatus
) -> Rulebook:
    (tmp_path / name).write_bytes(make_pdf(1))
    stored = await db_session.scalar(select(Game).where(Game.name == game))
    if stored is None:
        stored = Game(name=game)
        db_session.add(stored)
        await db_session.flush()
    rulebook = Rulebook(
        game_id=stored.id,
        filename=name,
        storage_path=name,
        page_count=1,
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        status=status,
    )
    db_session.add(rulebook)
    await db_session.commit()
    return rulebook


async def test_reindex_ingests_every_rulebook_again(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.READY)
    await _add_rulebook(db_session, tmp_path, "Azul", "azul.pdf", RulebookStatus.FAILED)

    failed = await reindex(sessionmaker, tmp_path, lambda path: ELEMENTS, FakeEmbedder())

    statuses = (await db_session.scalars(select(Rulebook.status).order_by(Rulebook.id))).all()
    chunks = (await db_session.scalars(select(Chunk))).all()
    assert failed == 0
    assert statuses == [RulebookStatus.READY, RulebookStatus.READY]
    assert len(chunks) == 2
    assert capsys.readouterr().out.splitlines()[-1] == "reindexed 2 rulebooks, 0 failed"


async def test_reindex_with_a_game_ingests_only_its_rulebooks(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    catan = await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.FAILED)
    await _add_rulebook(db_session, tmp_path, "Azul", "azul.pdf", RulebookStatus.FAILED)
    parsed: list[str] = []

    def parse(path: Path) -> list[Element]:
        parsed.append(path.name)
        return ELEMENTS

    await reindex(sessionmaker, tmp_path, parse, FakeEmbedder(), game_id=catan.game_id)

    assert parsed == ["catan.pdf"]


async def test_reindex_prints_why_a_rulebook_failed(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.READY)

    def fail(path: Path) -> list[Element]:
        raise RuntimeError("parsing failed 3 times")

    failed = await reindex(sessionmaker, tmp_path, fail, FakeEmbedder())

    assert failed == 1
    assert capsys.readouterr().out.splitlines() == [
        f"rulebook {rulebook.id} (catan.pdf): failed: parsing failed 3 times",
        "reindexed 1 rulebooks, 1 failed",
    ]


def test_parser_reads_the_game_option() -> None:
    assert _parser().parse_args(["reindex", "--game", "3"]).game == 3
    assert _parser().parse_args(["reindex"]).game is None
