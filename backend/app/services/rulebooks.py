import asyncio
import hashlib
import logging
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook
from app.errors import NotFoundError, RuleViolationError
from app.ingestion.pdf_info import read_page_count
from app.schemas.rulebooks import RulebookUpdate

logger = logging.getLogger(__name__)


class RulebookNotFoundError(NotFoundError):
    """Raised when no rulebook has the requested id."""


class InvalidMoveError(RuleViolationError):
    """Raised when a rulebook is moved to a game that doesn't exist."""


class DuplicateRulebookError(RuleViolationError):
    """Raised when the uploaded PDF is already stored as a rulebook."""


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def remove_files(upload_dir: Path, storage_paths: Iterable[str]) -> None:
    """Delete stored PDFs; a missing file is skipped and one that can't be removed is logged."""
    for name in storage_paths:
        try:
            await asyncio.to_thread((upload_dir / name).unlink, missing_ok=True)
        except OSError:
            logger.warning("could not remove %s", name, exc_info=True)


async def add_rulebook(
    session: AsyncSession, game: Game, filename: str, data: bytes, upload_dir: Path
) -> Rulebook:
    """Store a PDF as one of the game's rulebooks; nothing is kept if any step fails."""
    sha256 = hashlib.sha256(data).hexdigest()

    existing = (
        await session.execute(
            select(Rulebook, Game.name)
            .join(Game, Rulebook.game_id == Game.id)
            .where(Rulebook.sha256 == sha256)
        )
    ).first()
    if existing is not None:
        duplicate, game_name = existing
        raise DuplicateRulebookError(
            f"this PDF is already in the library, for {game_name}",
            duplicate_of={
                "rulebook_id": duplicate.id,
                "game_id": duplicate.game_id,
                "name": game_name,
            },
        )

    page_count = read_page_count(data)

    # Write the file before the row: a leftover file is harmless (the same PDF always gets
    # the same name), but a row pointing at a missing file would break ingestion.
    storage_path = f"{sha256}.pdf"
    path = upload_dir / storage_path
    await asyncio.to_thread(_write_file, path, data)

    rulebook = Rulebook(
        game_id=game.id,
        filename=filename,
        storage_path=storage_path,
        page_count=page_count,
        sha256=sha256,
    )
    try:
        session.add(rulebook)
        await session.commit()
    except Exception:
        await asyncio.to_thread(path.unlink, missing_ok=True)
        raise
    return rulebook


async def get_rulebook(session: AsyncSession, rulebook_id: int) -> Rulebook:
    """Return the rulebook with its id, or raise RulebookNotFoundError."""
    rulebook = await session.get(Rulebook, rulebook_id)
    if rulebook is None:
        raise RulebookNotFoundError(f"rulebook {rulebook_id} does not exist")
    return rulebook


async def list_rulebooks(
    session: AsyncSession, game_id: int | None = None
) -> list[tuple[Rulebook, str]]:
    """Return all rulebooks or rulebooks that match this game id."""

    statement = (
        select(Rulebook, Game.name)
        .join(Game, Rulebook.game_id == Game.id)
        .order_by(Game.name, Rulebook.filename)
    )

    if game_id is not None:
        statement = statement.where(Rulebook.game_id == game_id)

    result = await session.execute(statement)
    return [(rulebook, name) for rulebook, name in result.all()]


async def update_rulebook(
    session: AsyncSession, rulebook: Rulebook, data: RulebookUpdate
) -> Rulebook:
    """Rename a rulebook or move it to another game; only the fields sent change."""
    changes = data.model_dump(exclude_unset=True)

    if "game_id" in changes and await session.get(Game, changes["game_id"]) is None:
        raise InvalidMoveError(f"game {changes['game_id']} does not exist")

    for field, value in changes.items():
        setattr(rulebook, field, value)
    await session.commit()
    return rulebook


async def delete_rulebook(session: AsyncSession, rulebook: Rulebook, upload_dir: Path) -> None:
    """Delete a rulebook and its stored PDF."""
    storage_path = rulebook.storage_path
    await session.delete(rulebook)
    await session.commit()
    await remove_files(upload_dir, [storage_path])
