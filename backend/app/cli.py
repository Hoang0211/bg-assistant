"""Engine commands for the terminal: reindex, eval-ingest, eval, eval-text and eval-answers."""

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
from app.evaluation.answers import (
    AnswerResult,
    check_answer,
    format_answer_details,
    format_answer_report,
)
from app.evaluation.database import create_database_if_missing, eval_database_url, migrate
from app.evaluation.library import load_library, read_library
from app.evaluation.questions import read_questions
from app.evaluation.report import format_report
from app.evaluation.retrieval import evaluate_question
from app.evaluation.text_overlap import (
    RulebookOverlap,
    format_text_report,
    least_kept_first,
    rulebook_overlaps,
)
from app.ingestion.embedder import BgeEmbedder, Embedder
from app.ingestion.parsers import LlmParser, RulebookParser
from app.ingestion.pipeline import ingest_rulebook
from app.llm.base import create_llm_provider
from app.log_setup import configure_logging


async def reindex(
    sessionmaker: async_sessionmaker[AsyncSession],
    upload_dir: Path,
    parser: RulebookParser,
    embedder: Embedder,
    game_id: int | None = None,
    reparse: bool = False,
) -> int:
    """Ingest the stored rulebooks again, one at a time; return how many failed.

    With `reparse`, stored Markdown is ignored, so the parser reads every page again.
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


_REPARSE_HELP = "ignore stored Markdown, so the model reads every page again (and is paid)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    reindex_parser = commands.add_parser(
        "reindex", help="parse, chunk and embed the stored rulebooks again"
    )
    reindex_parser.add_argument("--game", type=int, help="only this game's rulebooks")
    reindex_parser.add_argument("--reparse", action="store_true", help=_REPARSE_HELP)
    eval_ingest_parser = commands.add_parser(
        "eval-ingest", help="build the eval database from the eval library and ingest it"
    )
    eval_ingest_parser.add_argument("--reparse", action="store_true", help=_REPARSE_HELP)
    commands.add_parser("eval", help="search the eval database for each golden question")
    commands.add_parser(
        "eval-text", help="compare the eval rulebooks' Markdown with each PDF page's text layer"
    )
    commands.add_parser(
        "eval-answers", help="answer each golden question from its chunks and grade it (paid)"
    )
    return parser


def _eval_settings(settings: Settings) -> Settings:
    """The settings for the eval database, on the same server as the dev database."""
    url = eval_database_url(settings.database_url, settings.eval_database_name)
    return settings.model_copy(update={"database_url": url})


async def _reindex(settings: Settings, game_id: int | None, reparse: bool) -> int:
    engine = create_db_engine(settings)
    try:
        failed = await reindex(
            create_sessionmaker(engine),
            settings.upload_dir,
            LlmParser(settings),
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
            LlmParser(settings),
            BgeEmbedder(settings.embedding_model),
            reparse=reparse,
        )
    finally:
        await engine.dispose()
    return 1 if failed else 0


def _write_report(settings: Settings, name: str, report: str) -> None:
    path = settings.eval_dir / "reports" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(f"wrote {path}")


async def _eval(settings: Settings) -> int:
    """Score each golden question's search results and write the report."""
    questions = read_questions(settings.eval_dir / "golden_questions.json")
    embedder = BgeEmbedder(settings.embedding_model)
    engine = create_db_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            results = [
                await evaluate_question(session, embedder, question, settings.search_results)
                for question in questions
            ]
            chunk_count = await session.scalar(select(func.count()).select_from(Chunk))
    finally:
        await engine.dispose()
    now = datetime.now()
    report = format_report(results, chunk_count or 0, settings, now)
    _write_report(settings, f"{now:%Y-%m-%d-%H%M}-retrieval.md", report)
    return 0


# How many of the least-kept pages have their words printed; the report has counts only, since
# it's committed and the rulebooks' text isn't.
_PAGES_TO_PRINT = 5
_WORDS_TO_PRINT = 15


def _print_words(rulebooks: list[RulebookOverlap]) -> None:
    for filename, page in least_kept_first(rulebooks)[:_PAGES_TO_PRINT]:
        missing = [word for word, _ in page.missing.most_common(_WORDS_TO_PRINT)]
        added = [word for word, _ in page.added.most_common(_WORDS_TO_PRINT)]
        print(f"{filename} p. {page.page}, kept {page.kept:.0%}")
        print(f"  missing: {' '.join(missing) or '-'}")
        print(f"  added: {' '.join(added) or '-'}")


async def _eval_text(settings: Settings) -> int:
    """Compare the eval database's Markdown with each PDF's text layer; write the report."""
    min_chars = settings.eval_text_min_page_chars
    engine = create_db_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            rulebooks = await rulebook_overlaps(session, settings.eval_rulebooks_dir, min_chars)
    finally:
        await engine.dispose()
    _print_words(rulebooks)
    now = datetime.now()
    report = format_text_report(rulebooks, min_chars, now)
    _write_report(settings, f"{now:%Y-%m-%d-%H%M}-text.md", report)
    return 0


async def _eval_answers(settings: Settings) -> int:
    """Answer and grade each golden question; write the report and, git-ignored, the answers."""
    questions = read_questions(settings.eval_dir / "golden_questions.json")
    embedder = BgeEmbedder(settings.embedding_model)
    llm = create_llm_provider(settings)
    results: list[AnswerResult] = []
    engine = create_db_engine(settings)
    try:
        async with create_sessionmaker(engine)() as session:
            for question in questions:
                result = await check_answer(session, embedder, llm, settings, question)
                print(f"{question.id}: {result.verdict}")
                results.append(result)
    finally:
        await engine.dispose()
    now = datetime.now()
    report = format_answer_report(results, settings, now)
    _write_report(settings, f"{now:%Y-%m-%d-%H%M}-answers.md", report)
    details = settings.eval_answers_dir / f"{now:%Y-%m-%d-%H%M}-answers.md"
    details.parent.mkdir(parents=True, exist_ok=True)
    details.write_text(format_answer_details(results, now), encoding="utf-8")
    print(f"wrote {details}")
    input_tokens = sum(result.input_tokens for result in results)
    output_tokens = sum(result.output_tokens for result in results)
    print(f"used {input_tokens} input and {output_tokens} output tokens")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    settings = get_settings()
    # Async psycopg on Windows needs the selector event loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    if args.command == "reindex":
        return asyncio.run(_reindex(settings, args.game, args.reparse), loop_factory=loop_factory)

    # The eval commands work on their own database, on the same server.
    eval_settings = _eval_settings(settings)
    if args.command == "eval-ingest":
        # Alembic runs its own event loop, so the database is made ready before ours starts.
        create_database_if_missing(eval_settings.database_url)
        migrate(eval_settings.database_url)
        return asyncio.run(_eval_ingest(eval_settings, args.reparse), loop_factory=loop_factory)

    if args.command == "eval-text":
        return asyncio.run(_eval_text(eval_settings), loop_factory=loop_factory)

    if args.command == "eval-answers":
        return asyncio.run(_eval_answers(eval_settings), loop_factory=loop_factory)

    return asyncio.run(_eval(eval_settings), loop_factory=loop_factory)


if __name__ == "__main__":
    sys.exit(main())
