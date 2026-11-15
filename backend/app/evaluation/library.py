"""The eval library: the games and rulebooks just eval-ingest builds its database from."""

import hashlib
import logging
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook
from app.ingestion.pdf_info import read_page_count

logger = logging.getLogger(__name__)


class LibraryRulebook(BaseModel):
    file: str  # the PDF's name in the rulebooks folder
    sha256: str  # of the edition the golden questions were written from


class LibraryExpansion(BaseModel):
    name: str
    rulebooks: list[LibraryRulebook]


class LibraryGame(BaseModel):
    name: str
    rulebooks: list[LibraryRulebook]
    expansions: list[LibraryExpansion]


class Library(BaseModel):
    games: list[LibraryGame]


def read_library(path: Path) -> Library:
    return Library.model_validate_json(path.read_text(encoding="utf-8"))


def _add_rulebooks(
    session: AsyncSession, game: Game, rulebooks: list[LibraryRulebook], rulebooks_dir: Path
) -> None:
    for entry in rulebooks:
        data = (rulebooks_dir / entry.file).read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        if sha256 != entry.sha256:
            logger.warning(
                "%s isn't the edition the golden questions were written from (its sha256 differs)",
                entry.file,
            )
        session.add(
            Rulebook(
                game_id=game.id,
                filename=entry.file,
                storage_path=entry.file,
                page_count=read_page_count(data),
                sha256=sha256,
            )
        )


async def load_library(session: AsyncSession, library: Library, rulebooks_dir: Path) -> None:
    """Replace every game in the database with the library's games and their rulebooks."""
    # Deleting the games cascades to their rulebooks and chunks; the PDFs aren't touched.
    await session.execute(delete(Game))
    for entry in library.games:
        game = Game(name=entry.name)
        session.add(game)
        await session.flush()
        _add_rulebooks(session, game, entry.rulebooks, rulebooks_dir)
        for expansion_entry in entry.expansions:
            expansion = Game(name=expansion_entry.name, is_expansion=True, base_game_id=game.id)
            session.add(expansion)
            await session.flush()
            _add_rulebooks(session, expansion, expansion_entry.rulebooks, rulebooks_dir)
    await session.commit()
