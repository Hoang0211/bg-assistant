from fastapi import Request

from app.db.session import database_is_reachable


async def get_database_reachable(request: Request) -> bool:
    """Dependency: whether the app's database is reachable right now."""
    return await database_is_reachable(request.app.state.engine)
