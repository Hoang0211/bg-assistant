import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook, RulebookStatus
from app.evaluation.library import (
    Library,
    LibraryExpansion,
    LibraryGame,
    LibraryRulebook,
    load_library,
    read_library,
)
from tests.helpers import make_pdf


def _rulebook(tmp_path: Path, file: str, pages: int = 1) -> LibraryRulebook:
    data = make_pdf(pages)
    (tmp_path / file).write_bytes(data)
    return LibraryRulebook(file=file, sha256=hashlib.sha256(data).hexdigest())


def test_read_library_reads_games_and_their_expansions(tmp_path: Path) -> None:
    path = tmp_path / "library.json"
    path.write_text(
        '{"about": "ignored", "games": [{"name": "Base", "rulebooks": [{"file": "base.pdf",'
        ' "sha256": "a"}], "expansions": [{"name": "Exp", "rulebooks": []}]}]}',
        encoding="utf-8",
    )

    library = read_library(path)

    assert library == Library(
        games=[
            LibraryGame(
                name="Base",
                rulebooks=[LibraryRulebook(file="base.pdf", sha256="a")],
                expansions=[LibraryExpansion(name="Exp", rulebooks=[])],
            )
        ]
    )


async def test_load_library_creates_the_games_and_links_expansions(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    library = Library(
        games=[
            LibraryGame(
                name="Base",
                rulebooks=[_rulebook(tmp_path, "base.pdf")],
                expansions=[LibraryExpansion(name="Exp", rulebooks=[])],
            ),
            LibraryGame(name="Other", rulebooks=[], expansions=[]),
        ]
    )

    await load_library(db_session, library, tmp_path)

    games = (
        await db_session.execute(
            select(Game.name, Game.is_expansion, Game.base_game_id).order_by(Game.id)
        )
    ).all()
    base_id = await db_session.scalar(select(Game.id).where(Game.name == "Base"))
    assert games == [("Base", False, None), ("Exp", True, base_id), ("Other", False, None)]


async def test_load_library_adds_each_rulebook_pointing_at_its_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = _rulebook(tmp_path, "base.pdf", pages=3)
    library = Library(games=[LibraryGame(name="Base", rulebooks=[rulebook], expansions=[])])

    await load_library(db_session, library, tmp_path)

    rows = (
        await db_session.execute(
            select(
                Rulebook.filename,
                Rulebook.storage_path,
                Rulebook.page_count,
                Rulebook.sha256,
                Rulebook.status,
            )
        )
    ).all()
    assert rows == [("base.pdf", "base.pdf", 3, rulebook.sha256, RulebookStatus.UPLOADED)]


async def test_load_library_replaces_the_games_already_there(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    db_session.add(Game(name="Old"))
    await db_session.commit()
    library = Library(games=[LibraryGame(name="Base", rulebooks=[], expansions=[])])

    await load_library(db_session, library, tmp_path)

    assert list(await db_session.scalars(select(Game.name))) == ["Base"]


async def test_load_library_warns_when_a_file_is_another_edition(
    db_session: AsyncSession, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "base.pdf").write_bytes(make_pdf(1))
    library = Library(
        games=[
            LibraryGame(
                name="Base",
                rulebooks=[LibraryRulebook(file="base.pdf", sha256="0" * 64)],
                expansions=[],
            )
        ]
    )

    await load_library(db_session, library, tmp_path)

    assert [record.getMessage() for record in caplog.records] == [
        "base.pdf isn't the edition the golden questions were written from (its sha256 differs)"
    ]
    assert await db_session.scalar(select(Rulebook.filename)) == "base.pdf"
