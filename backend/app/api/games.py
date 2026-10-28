from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.deps import SessionDep
from app.schemas.games import GameCreate, GameFilters, GameRead, GameUpdate
from app.services import games as games_service

router = APIRouter(prefix="/games", tags=["games"])


@router.get("")
async def list_games(
    filters: Annotated[GameFilters, Query()], session: SessionDep
) -> list[GameRead]:
    """Return the games matching every filter given, sorted by name."""
    games = await games_service.list_games(session, filters)
    return [GameRead.model_validate(game) for game in games]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_game(data: GameCreate, session: SessionDep) -> GameRead:
    """Create one game."""
    game = await games_service.create_game(session, data)
    return GameRead.model_validate(game)


@router.get("/{game_id}")
async def get_game(game_id: int, session: SessionDep) -> GameRead:
    """Return one game."""
    game = await games_service.get_game(session, game_id)
    return GameRead.model_validate(game)


@router.patch("/{game_id}")
async def update_game(game_id: int, data: GameUpdate, session: SessionDep) -> GameRead:
    """Change only the fields sent; the merged game is validated as a whole."""
    game = await games_service.get_game(session, game_id)
    try:
        game = await games_service.update_game(session, game, data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    return GameRead.model_validate(game)


@router.delete("/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game(game_id: int, session: SessionDep) -> None:
    """Delete a game and its rulebooks; its expansions are kept and unlinked."""
    game = await games_service.get_game(session, game_id)
    await games_service.delete_game(session, game)
