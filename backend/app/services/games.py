from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Game, Rulebook
from app.errors import NotFoundError, RuleViolationError
from app.schemas.games import GameCreate, GameFilters, GameUpdate
from app.services.rulebooks import remove_files


class GameNotFoundError(NotFoundError):
    """Raised when no game has the requested id."""


class InvalidExpansionError(RuleViolationError):
    """Raised when a game's expansion link breaks a library rule."""


async def _check_expansion_link(session: AsyncSession, base_game_id: int | None) -> None:
    """Check that an expansion's base game exists and is itself a base game."""
    if base_game_id is None:
        return
    base_game = await session.get(Game, base_game_id)
    if base_game is None:
        raise InvalidExpansionError(f"base game {base_game_id} does not exist")
    if base_game.is_expansion:
        raise InvalidExpansionError("the base game is itself an expansion")


async def create_game(session: AsyncSession, data: GameCreate) -> Game:
    """Add a game to the library, after checking its expansion link."""
    await _check_expansion_link(session, data.base_game_id)
    game = Game(**data.model_dump())
    session.add(game)
    await session.commit()
    return game


async def get_game(session: AsyncSession, game_id: int) -> Game:
    """Return the game with this id, or raise GameNotFoundError."""
    game = await session.get(Game, game_id)
    if game is None:
        raise GameNotFoundError(f"game {game_id} does not exist")
    return game


async def list_games(session: AsyncSession, filters: GameFilters) -> list[Game]:
    """Return the games matching every filter given, sorted by name."""

    statement = select(Game).order_by(Game.name)
    if filters.q:
        statement = statement.where(Game.name.icontains(filters.q, autoescape=True))
    if filters.players is not None:
        statement = statement.where(
            Game.min_players <= filters.players, Game.max_players >= filters.players
        )
    if filters.genres:
        statement = statement.where(Game.genres.overlap(filters.genres))
    if filters.base_game_id is not None:
        statement = statement.where(Game.base_game_id == filters.base_game_id)

    result = await session.scalars(statement)
    return list(result.all())


async def update_game(session: AsyncSession, game: Game, data: GameUpdate) -> Game:
    """Apply a partial update, validating the merged result before saving it."""
    current = GameCreate.model_validate(game, from_attributes=True).model_dump()
    changes = data.model_dump(exclude_unset=True)
    merged = GameCreate.model_validate({**current, **changes})

    await _check_expansion_link(session, merged.base_game_id)

    if (
        merged.is_expansion
        and not game.is_expansion
        and await session.scalar(select(exists().where(Game.base_game_id == game.id)))
    ):
        raise InvalidExpansionError("a game with expansions cannot become an expansion")

    for field, value in merged.model_dump().items():
        setattr(game, field, value)
    await session.commit()
    return game


async def delete_game(session: AsyncSession, game: Game, upload_dir: Path) -> None:
    """Remove a game; its rulebooks are deleted and its expansions unlinked by the database."""
    storage_paths = list(
        await session.scalars(select(Rulebook.storage_path).where(Rulebook.game_id == game.id))
    )
    await session.delete(game)
    await session.commit()
    await remove_files(upload_dir, storage_paths)
