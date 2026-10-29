from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import database_is_reachable


async def get_database_reachable(request: Request) -> bool:
    """Dependency: whether the app's database is reachable right now."""
    return await database_is_reachable(request.app.state.engine)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Open a database session for one request and close it afterwards."""
    async with request.app.state.sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_upload_dir() -> Path:
    """Dependency: the folder where rulebook PDFs are stored."""
    return get_settings().upload_dir


UploadDirDep = Annotated[Path, Depends(get_upload_dir)]
