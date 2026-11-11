"""The stored rulebook PDFs: writing and removing them under upload_dir."""

import asyncio
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)


def write_file(path: Path, data: bytes) -> None:
    """Write a file, creating its folder first if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def remove_files(upload_dir: Path, storage_paths: Iterable[str]) -> None:
    """Delete stored PDFs; a missing file is skipped and one that can't be removed is logged."""
    for name in storage_paths:
        try:
            await asyncio.to_thread((upload_dir / name).unlink, missing_ok=True)
        except OSError:
            logger.warning("could not remove %s", name, exc_info=True)
