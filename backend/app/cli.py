"""Engine commands for the terminal: python -m app.cli reindex [--game <id>]."""

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Rulebook, RulebookStatus
from app.db.session import create_db_engine, create_sessionmaker
from app.ingestion.elements import Element
from app.ingestion.embedder import BgeEmbedder, Embedder
from app.ingestion.parse_process import parse_in_process
from app.ingestion.pipeline import ingest_rulebook
from app.log_setup import configure_logging


async def reindex(
    sessionmaker: async_sessionmaker[AsyncSession],
    upload_dir: Path,
    parse: Callable[[Path], list[Element]],
    embedder: Embedder,
    game_id: int | None = None,
) -> int:
    """Ingest the stored rulebooks again, one at a time; return how many failed."""
    query = select(Rulebook.id).order_by(Rulebook.id)
    if game_id is not None:
        query = query.where(Rulebook.game_id == game_id)
    async with sessionmaker() as session:
        ids = (await session.scalars(query)).all()

    failed = 0
    skipped = 0
    for rulebook_id in ids:
        async with sessionmaker() as session:
            await ingest_rulebook(session, rulebook_id, upload_dir, parse, embedder)
            # A fresh query: after a failure the loaded rulebook is expired and can't lazy-load.
            row = (
                await session.execute(
                    select(
                        Rulebook.filename, Rulebook.status, Rulebook.error, Rulebook.parse_report
                    ).where(Rulebook.id == rulebook_id)
                )
            ).one_or_none()
        if row is None:
            print(f"rulebook {rulebook_id}: deleted, skipped")
            skipped += 1
            continue
        filename, status, error, report = row
        if status == RulebookStatus.READY:
            assert report is not None
            print(f"rulebook {rulebook_id} ({filename}): ready, {report['chunk_count']} chunks")
        else:
            failed += 1
            print(f"rulebook {rulebook_id} ({filename}): failed: {error}")

    print(f"reindexed {len(ids) - skipped} rulebooks, {failed} failed")
    return failed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    reindex_parser = commands.add_parser(
        "reindex", help="parse, chunk and embed the stored rulebooks again"
    )
    reindex_parser.add_argument("--game", type=int, help="only this game's rulebooks")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_db_engine(settings)
    try:
        failed = await reindex(
            create_sessionmaker(engine),
            settings.upload_dir,
            partial(
                parse_in_process,
                attempts=settings.parse_attempts,
                timeout_seconds=settings.parse_timeout_seconds,
            ),
            BgeEmbedder(settings.embedding_model),
            args.game,
        )
    finally:
        await engine.dispose()
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    # Async psycopg on Windows needs the selector event loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    return asyncio.run(_run(args), loop_factory=loop_factory)


if __name__ == "__main__":
    sys.exit(main())
