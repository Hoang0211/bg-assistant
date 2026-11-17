"""Engine commands for the terminal: reindex [--game <id>], eval-ingest and eval."""

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import partial
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import Chunk, Rulebook, RulebookStatus
from app.db.session import create_db_engine, create_sessionmaker
from app.evaluation.database import create_database_if_missing, eval_database_url, migrate
from app.evaluation.library import load_library, read_library
from app.evaluation.questions import read_questions
from app.evaluation.report import format_report
from app.evaluation.retrieval import evaluate_question
from app.ingestion.elements import Element
from app.ingestion.embedder import BgeEmbedder, Embedder
from app.ingestion.parse_process import parse_in_process
from app.ingestion.pipeline import ingest_rulebook
from app.log_setup import configure_logging
from app.retrieval.reranker import BgeReranker


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
    commands.add_parser("eval", help="search the eval database for each golden question")
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


async def _eval(settings: Settings) -> int:
    """Score each golden question's search results, without and with reranking; write the report."""
    questions = read_questions(settings.eval_dir / "golden_questions.json")
    embedder = BgeEmbedder(settings.embedding_model)
    reranker = BgeReranker(settings.reranker_model)
    engine = create_db_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            hybrid = [
                await evaluate_question(session, embedder, None, question, settings.search_results)
                for question in questions
            ]
            reranked = [
                await evaluate_question(
                    session, embedder, reranker, question, settings.search_results
                )
                for question in questions
            ]
            chunk_count = await session.scalar(select(func.count()).select_from(Chunk))
    finally:
        await engine.dispose()
    now = datetime.now()
    path = settings.eval_dir / "reports" / f"{now:%Y-%m-%d-%H%M}-retrieval.md"
    path.parent.mkdir(exist_ok=True)
    report = format_report(hybrid, reranked, settings, chunk_count or 0, now)
    path.write_text(report, encoding="utf-8")
    print(f"wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    settings = get_settings()
    # The eval commands work on their own database, on the same server.
    eval_url = eval_database_url(settings.database_url, settings.eval_database_name)
    eval_settings = settings.model_copy(update={"database_url": eval_url})
    # Async psycopg on Windows needs the selector event loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    if args.command == "eval-ingest":
        # Alembic runs its own event loop, so the database is made ready before ours starts.
        create_database_if_missing(eval_url)
        migrate(eval_url)
        return asyncio.run(_eval_ingest(eval_settings), loop_factory=loop_factory)

    if args.command == "eval":
        return asyncio.run(_eval(eval_settings), loop_factory=loop_factory)

    return asyncio.run(_reindex(settings, args.game), loop_factory=loop_factory)


if __name__ == "__main__":
    sys.exit(main())
