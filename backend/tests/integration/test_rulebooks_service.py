from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook, RulebookStatus
from app.ingestion.pdf_info import InvalidPdfError
from app.schemas.games import GameCreate
from app.services.games import create_game
from app.services.rulebooks import DuplicateRulebookError, add_rulebook
from tests.pdfs import make_pdf


async def add_game(session: AsyncSession, name: str = "Game") -> Game:
    return await create_game(session, GameCreate(name=name))


async def test_add_rulebook_stores_the_file_and_its_details(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game = await add_game(db_session)
    data = make_pdf(3)

    rulebook = await add_rulebook(db_session, game, "rules.pdf", data, tmp_path)

    assert rulebook.game_id == game.id
    assert rulebook.filename == "rules.pdf"
    assert rulebook.page_count == 3
    assert rulebook.storage_path == f"{rulebook.sha256}.pdf"
    assert rulebook.status == RulebookStatus.UPLOADED
    assert (tmp_path / rulebook.storage_path).read_bytes() == data


async def test_add_rulebook_keeps_several_rulebooks_for_one_game(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game = await add_game(db_session)
    data_1 = make_pdf(3)
    data_2 = make_pdf(1)

    rulebook_1 = await add_rulebook(db_session, game, "rules_1.pdf", data_1, tmp_path)
    rulebook_2 = await add_rulebook(db_session, game, "rules_2.pdf", data_2, tmp_path)

    assert rulebook_1.game_id == game.id
    assert rulebook_2.game_id == game.id
    assert rulebook_1.id != rulebook_2.id
    assert len(list(tmp_path.iterdir())) == 2


async def test_add_rulebook_rejects_a_duplicate_even_for_another_game(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game_1 = await add_game(db_session, "Game 1")
    game_2 = await add_game(db_session, "Game 2")
    data = make_pdf(3)

    rulebook_1 = await add_rulebook(db_session, game_1, "rules.pdf", data, tmp_path)

    with pytest.raises(DuplicateRulebookError) as exc_info:
        await add_rulebook(db_session, game_2, "copy.pdf", data, tmp_path)

    assert exc_info.value.extra == {
        "duplicate_of": {"rulebook_id": rulebook_1.id, "game_id": game_1.id, "name": "Game 1"}
    }
    assert len(list(tmp_path.iterdir())) == 1


async def test_add_rulebook_rejects_an_unreadable_pdf_and_stores_nothing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game = await add_game(db_session)

    with pytest.raises(InvalidPdfError, match="not a readable PDF"):
        await add_rulebook(db_session, game, "rules.pdf", b"not a pdf", tmp_path)

    assert list(tmp_path.iterdir()) == []
    assert await db_session.scalar(select(func.count()).select_from(Rulebook)) == 0


async def test_add_rulebook_removes_the_file_when_the_commit_fails(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = await add_game(db_session)
    data = make_pdf(1)

    async def fail() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db_session, "commit", fail)

    with pytest.raises(RuntimeError):
        await add_rulebook(db_session, game, "rules.pdf", data, tmp_path)

    assert list(tmp_path.iterdir()) == []
