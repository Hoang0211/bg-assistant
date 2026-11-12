"""Engine commands for the terminal: python -m app.cli reindex [--game <id>] | eval-ingest."""

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import Rulebook, RulebookStatus
from app.db.session import create_db_engine, create_sessionmaker
from app.evaluation.database import create_database_if_missing, eval_database_url, migrate
from app.evaluation.library import load_library, read_library
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
    commands.add_parser(
        "eval-ingest", help="build the eval database from the eval library and ingest it"
    )
    return parser


def _parse(settings: Settings) -> Callable[[Path], list[Element]]:
    return partial(
        parse_in_process,
        attempts=settings.parse_attempts,
        timeout_seconds=settings.parse_timeout_seconds,
    )


async def _reindex(settings: Settings, game_id: int | None) -> int:
    engine = create_db_engine(settings)
    try:
        failed = await reindex(
            create_sessionmaker(engine),
            settings.upload_dir,
            _parse(settings),
            BgeEmbedder(settings.embedding_model),
            game_id,
        )
    finally:
        await engine.dispose()
    return 1 if failed else 0


async def _eval_ingest(settings: Settings) -> int:
    """Replace the eval database's games with the eval library and ingest its rulebooks."""
    engine = create_db_engine(settings)
    try:
        sessionmaker = create_sessionmaker(engine)
        async with sessionmaker() as session:
            library = read_library(settings.eval_dir / "library.json")
            await load_library(session, library, settings.eval_rulebooks_dir)
        failed = await reindex(
            sessionmaker,
            settings.eval_rulebooks_dir,
            _parse(settings),
            BgeEmbedder(settings.embedding_model),
        )
    finally:
        await engine.dispose()
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    settings = get_settings()
    # Async psycopg on Windows needs the selector event loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    if args.command == "eval-ingest":
        url = eval_database_url(settings.database_url, settings.eval_database_name)
        # Alembic runs its own event loop, so the database is made ready before ours starts.
        create_database_if_missing(url)
        migrate(url)
        eval_settings = settings.model_copy(update={"database_url": url})
        return asyncio.run(_eval_ingest(eval_settings), loop_factory=loop_factory)
    return asyncio.run(_reindex(settings, args.game), loop_factory=loop_factory)


if __name__ == "__main__":
    sys.exit(main())
