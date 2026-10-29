import asyncio
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook
from app.errors import RuleViolationError
from app.ingestion.pdf_info import read_page_count


class DuplicateRulebookError(RuleViolationError):
    """Raised when the uploaded PDF is already stored as a rulebook."""


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


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
