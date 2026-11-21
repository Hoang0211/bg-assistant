"""Engine commands for the terminal: reindex, eval-ingest and eval."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import Chunk, Rulebook, RulebookStatus
from app.db.session import create_db_engine, create_sessionmaker
from app.evaluation.database import create_database_if_missing, eval_database_url, migrate
from app.evaluation.library import load_library, read_library
from app.evaluation.questions import read_questions
from app.evaluation.report import ParserResults, format_comparison, format_report
from app.evaluation.retrieval import evaluate_question
from app.ingestion.embedder import BgeEmbedder, Embedder
from app.ingestion.parsers import RulebookParser, create_parser
from app.ingestion.pipeline import ingest_rulebook
from app.log_setup import configure_logging
from app.retrieval.reranker import BgeReranker, Reranker


async def reindex(
    sessionmaker: async_sessionmaker[AsyncSession],
    upload_dir: Path,
    parser: RulebookParser,
    embedder: Embedder,
    game_id: int | None = None,
    reparse: bool = False,
) -> int:
    """Ingest the stored rulebooks again, one at a time; return how many failed.

    With `reparse`, stored Markdown is ignored, so the LLM parser reads every page again.
    """
    query = select(Rulebook.id).order_by(Rulebook.id)
    if game_id is not None:
        query = query.where(Rulebook.game_id == game_id)
    async with sessionmaker() as session:
        ids = (await session.scalars(query)).all()

    failed = 0
    skipped = 0
    for rulebook_id in ids:
        async with sessionmaker() as session:
            await ingest_rulebook(session, rulebook_id, upload_dir, parser, embedder, reparse)
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


_PARSERS = ["docling", "llm"]
_PARSER_HELP = "the parser whose eval database to use (default: the pdf_parser setting)"
_REPARSE_HELP = "ignore stored Markdown, so the LLM parser reads every page again (and is paid)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    reindex_parser = commands.add_parser(
        "reindex", help="parse, chunk and embed the stored rulebooks again"
    )
    reindex_parser.add_argument("--game", type=int, help="only this game's rulebooks")
    reindex_parser.add_argument("--reparse", action="store_true", help=_REPARSE_HELP)
    eval_ingest_parser = commands.add_parser(
        "eval-ingest", help="build a parser's eval database from the eval library and ingest it"
    )
    eval_ingest_parser.add_argument("--parser", choices=_PARSERS, help=_PARSER_HELP)
    eval_ingest_parser.add_argument("--reparse", action="store_true", help=_REPARSE_HELP)
    eval_parser = commands.add_parser(
        "eval", help="search a parser's eval database for each golden question"
    )
    eval_options = eval_parser.add_mutually_exclusive_group()
    eval_options.add_argument("--parser", choices=_PARSERS, help=_PARSER_HELP)
    eval_options.add_argument(
        "--compare", action="store_true", help="score every parser's database, side by side"
    )
    return parser


def _eval_settings(settings: Settings, pdf_parser: str) -> Settings:
    """The settings for one parser's eval database, on the same server as the dev database."""
    name = f"{settings.eval_database_name}_{pdf_parser}"
    url = eval_database_url(settings.database_url, name)
    return settings.model_copy(update={"database_url": url, "pdf_parser": pdf_parser})


async def _reindex(settings: Settings, game_id: int | None, reparse: bool) -> int:
    engine = create_db_engine(settings)
    try:
        failed = await reindex(
            create_sessionmaker(engine),
            settings.upload_dir,
            create_parser(settings),
            BgeEmbedder(settings.embedding_model),
            game_id,
            reparse,
        )
    finally:
        await engine.dispose()
    return 1 if failed else 0


async def _eval_ingest(settings: Settings, reparse: bool) -> int:
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
            create_parser(settings),
            BgeEmbedder(settings.embedding_model),
            reparse=reparse,
        )
    finally:
        await engine.dispose()
    return 1 if failed else 0


async def _search_parser(
    settings: Settings, embedder: Embedder, reranker: Reranker
) -> ParserResults:
    """Search one parser's eval database for each golden question, without and with reranking."""
    questions = read_questions(settings.eval_dir / "golden_questions.json")
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
    return ParserResults(settings.pdf_parser, chunk_count or 0, hybrid, reranked)


def _write_report(settings: Settings, name: str, report: str) -> None:
    path = settings.eval_dir / "reports" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(f"wrote {path}")


async def _eval(settings: Settings) -> int:
    """Score each golden question's search results, without and with reranking; write the report."""
    embedder = BgeEmbedder(settings.embedding_model)
    reranker = BgeReranker(settings.reranker_model)
    results = await _search_parser(settings, embedder, reranker)
    now = datetime.now()
    report = format_report(results, settings, now)
    _write_report(settings, f"{now:%Y-%m-%d-%H%M}-retrieval.md", report)
    return 0


async def _compare(settings: Settings) -> int:
    """Score each parser's eval database the same way and write them side by side."""
    embedder = BgeEmbedder(settings.embedding_model)
    reranker = BgeReranker(settings.reranker_model)
    first, second = [
        await _search_parser(_eval_settings(settings, parser), embedder, reranker)
        for parser in _PARSERS
    ]
    now = datetime.now()
    report = format_comparison(first, second, settings, now)
    _write_report(settings, f"{now:%Y-%m-%d-%H%M}-comparison.md", report)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    settings = get_settings()
    # Async psycopg on Windows needs the selector event loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    if args.command == "reindex":
        return asyncio.run(_reindex(settings, args.game, args.reparse), loop_factory=loop_factory)

    if args.command == "eval" and args.compare:
        return asyncio.run(_compare(settings), loop_factory=loop_factory)

    # Each parser's chunks are evaluated in their own database, so both stay ready to compare.
    eval_settings = _eval_settings(settings, args.parser or settings.pdf_parser)
    if args.command == "eval-ingest":
        # Alembic runs its own event loop, so the database is made ready before ours starts.
        create_database_if_missing(eval_settings.database_url)
        migrate(eval_settings.database_url)
        return asyncio.run(_eval_ingest(eval_settings, args.reparse), loop_factory=loop_factory)

    return asyncio.run(_eval(eval_settings), loop_factory=loop_factory)


if __name__ == "__main__":
    sys.exit(main())
