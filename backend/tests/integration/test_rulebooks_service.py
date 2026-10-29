from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook, RulebookStatus
from app.ingestion.pdf_info import InvalidPdfError
from app.schemas.games import GameCreate
from app.schemas.rulebooks import RulebookUpdate
from app.services.games import create_game
from app.services.rulebooks import (
    DuplicateRulebookError,
    InvalidMoveError,
    RulebookNotFoundError,
    add_rulebook,
    delete_rulebook,
    get_rulebook,
    list_rulebooks,
    update_rulebook,
)
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


async def test_get_rulebook_raises_for_an_unknown_id(db_session: AsyncSession) -> None:
    with pytest.raises(RulebookNotFoundError, match="999"):
        await get_rulebook(db_session, 999)


async def test_list_rulebooks_sorts_by_game_name_then_filename(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game_1 = await add_game(db_session, name="Game 1")
    game_2 = await add_game(db_session, name="Game 2")

    data_1 = make_pdf(1)
    data_2 = make_pdf(2)
    data_3 = make_pdf(3)

    rulebook_3 = await add_rulebook(db_session, game_2, "rules3.pdf", data_3, tmp_path)
    rulebook_2 = await add_rulebook(db_session, game_2, "rules2.pdf", data_2, tmp_path)
    rulebook_1 = await add_rulebook(db_session, game_1, "rules9.pdf", data_1, tmp_path)

    rulebooks = await list_rulebooks(db_session)

    assert rulebooks == [
        (rulebook_1, "Game 1"),
        (rulebook_2, "Game 2"),
        (rulebook_3, "Game 2"),
    ]


async def test_list_rulebooks_filters_by_game(db_session: AsyncSession, tmp_path: Path) -> None:
    game_1 = await add_game(db_session, name="Game 1")
    game_2 = await add_game(db_session, name="Game 2")

    data_1 = make_pdf(1)
    data_2 = make_pdf(2)
    data_3 = make_pdf(3)

    await add_rulebook(db_session, game_1, "rules1.pdf", data_1, tmp_path)
    rulebook_2 = await add_rulebook(db_session, game_2, "rules2.pdf", data_2, tmp_path)
    rulebook_3 = await add_rulebook(db_session, game_2, "rules3.pdf", data_3, tmp_path)

    rulebooks = await list_rulebooks(db_session, game_2.id)

    assert rulebooks == [
        (rulebook_2, "Game 2"),
        (rulebook_3, "Game 2"),
    ]


async def test_update_rulebook_renames_without_touching_the_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game = await add_game(db_session, name="Game")
    data = make_pdf(1)
    rulebook = await add_rulebook(db_session, game, "rules.pdf", data, tmp_path)
    storage_path = rulebook.storage_path

    await update_rulebook(db_session, rulebook, RulebookUpdate(filename="New file name"))

    assert rulebook.filename == "New file name"
    assert rulebook.storage_path == storage_path
    assert rulebook.game_id == game.id
    assert list(tmp_path.iterdir()) == [tmp_path / storage_path]
    assert (tmp_path / storage_path).read_bytes() == data


async def test_update_rulebook_moves_it_to_another_game(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game_1 = await add_game(db_session, name="Game 1")
    game_2 = await add_game(db_session, name="Game 2")
    data = make_pdf(1)
    rulebook = await add_rulebook(db_session, game_1, "rules.pdf", data, tmp_path)
    storage_path = rulebook.storage_path

    await update_rulebook(db_session, rulebook, RulebookUpdate(game_id=game_2.id))

    assert rulebook.filename == "rules.pdf"
    assert rulebook.storage_path == storage_path
    assert rulebook.game_id == game_2.id
    assert list(tmp_path.iterdir()) == [tmp_path / storage_path]
    assert (tmp_path / storage_path).read_bytes() == data


async def test_update_rulebook_rejects_a_move_to_a_missing_game(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game = await add_game(db_session, name="Game")
    data = make_pdf(1)
    rulebook = await add_rulebook(db_session, game, "rules.pdf", data, tmp_path)

    with pytest.raises(InvalidMoveError, match="999"):
        await update_rulebook(db_session, rulebook, RulebookUpdate(game_id=999))

    assert rulebook.game_id == game.id


async def test_delete_rulebook_removes_its_row_and_file(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game = await add_game(db_session)
    data = make_pdf(1)
    rulebook = await add_rulebook(db_session, game, "rules.pdf", data, tmp_path)
    rulebook_id = rulebook.id

    await delete_rulebook(db_session, rulebook, tmp_path)

    with pytest.raises(RulebookNotFoundError, match=str(rulebook_id)):
        await get_rulebook(db_session, rulebook_id)
    assert list(tmp_path.iterdir()) == []
    assert await db_session.get(Game, game.id) is not None


async def test_delete_rulebook_succeeds_when_its_file_is_already_gone(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    game = await add_game(db_session)
    data = make_pdf(1)
    rulebook = await add_rulebook(db_session, game, "rules.pdf", data, tmp_path)
    rulebook_id = rulebook.id
    (tmp_path / rulebook.storage_path).unlink()

    await delete_rulebook(db_session, rulebook, tmp_path)

    assert await db_session.get(Rulebook, rulebook_id) is None
