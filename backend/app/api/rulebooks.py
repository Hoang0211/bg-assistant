from fastapi import APIRouter, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import SessionDep, UploadDirDep
from app.db.models import Rulebook
from app.schemas.rulebooks import RulebookRead, RulebookUpdate
from app.services import games as games_service
from app.services import rulebooks as rulebooks_service

router = APIRouter(tags=["rulebooks"])


def _to_read(rulebook: Rulebook, game_name: str) -> RulebookRead:
    return RulebookRead(
        id=rulebook.id,
        game_id=rulebook.game_id,
        game_name=game_name,
        filename=rulebook.filename,
        page_count=rulebook.page_count,
        status=rulebook.status,
        error=rulebook.error,
        created_at=rulebook.created_at,
        updated_at=rulebook.updated_at,
    )


@router.get("/games/{game_id}/rulebooks")
async def list_game_rulebooks(game_id: int, session: SessionDep) -> list[RulebookRead]:
    """Return one game's rulebooks, sorted by filename."""
    await games_service.get_game(session, game_id)
    rows = await rulebooks_service.list_rulebooks(session, game_id)

    return [_to_read(rulebook, game_name) for rulebook, game_name in rows]


@router.post("/games/{game_id}/rulebooks", status_code=status.HTTP_201_CREATED)
async def add_rulebook(
    game_id: int, file: UploadFile, session: SessionDep, upload_dir: UploadDirDep
) -> RulebookRead:
    """Add a PDF as one of the game's rulebooks."""
    game = await games_service.get_game(session, game_id)
    data = await file.read()

    rulebook = await rulebooks_service.add_rulebook(
        session, game, file.filename or "rulebook.pdf", data, upload_dir
    )

    return _to_read(rulebook, game.name)


@router.get("/rulebooks")
async def list_rulebooks(session: SessionDep) -> list[RulebookRead]:
    """Return all rulebooks, sorted by game name, then filename."""
    rows = await rulebooks_service.list_rulebooks(session)

    return [_to_read(rulebook, game_name) for rulebook, game_name in rows]


@router.get("/rulebooks/{rulebook_id}/file", response_class=FileResponse)
async def get_rulebook_file(
    rulebook_id: int, session: SessionDep, upload_dir: UploadDirDep
) -> FileResponse:
    """Return the rulebook's PDF, with support for range requests."""
    rulebook = await rulebooks_service.get_rulebook(session, rulebook_id)
    game = await games_service.get_game(session, rulebook.game_id)

    return FileResponse(
        upload_dir / rulebook.storage_path,
        media_type="application/pdf",
        filename=f"{game.name} - {rulebook.filename}",
        content_disposition_type="inline",
    )


@router.patch("/rulebooks/{rulebook_id}")
async def update_rulebook(
    rulebook_id: int, data: RulebookUpdate, session: SessionDep
) -> RulebookRead:
    """Rename a rulebook or move it to another game; only the fields sent change."""
    rulebook = await rulebooks_service.get_rulebook(session, rulebook_id)
    rulebook = await rulebooks_service.update_rulebook(session, rulebook, data)
    game = await games_service.get_game(session, rulebook.game_id)

    return _to_read(rulebook, game.name)


@router.delete("/rulebooks/{rulebook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rulebook(rulebook_id: int, session: SessionDep, upload_dir: UploadDirDep) -> None:
    """Delete a rulebook and its stored PDF."""
    rulebook = await rulebooks_service.get_rulebook(session, rulebook_id)
    await rulebooks_service.delete_rulebook(session, rulebook, upload_dir)
