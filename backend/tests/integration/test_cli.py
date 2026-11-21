import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli import _eval_settings, _parser, reindex
from app.config import Settings
from app.db.models import Chunk, Game, Rulebook, RulebookStatus
from app.ingestion.elements import Element, ElementKind
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.parsers import FakeParser
from tests.helpers import DeletingParser, FailingParser, make_pdf

ELEMENTS = [Element(ElementKind.HEADING, "Setup", 1), Element(ElementKind.PARAGRAPH, "Roll.", 1)]


async def _add_rulebook(
    db_session: AsyncSession, tmp_path: Path, game: str, name: str, status: RulebookStatus
) -> Rulebook:
    (tmp_path / name).write_bytes(make_pdf(1))
    stored = await db_session.scalar(select(Game).where(Game.name == game))
    if stored is None:
        stored = Game(name=game)
        db_session.add(stored)
        await db_session.flush()
    rulebook = Rulebook(
        game_id=stored.id,
        filename=name,
        storage_path=name,
        page_count=1,
        sha256=hashlib.sha256(name.encode()).hexdigest(),
        status=status,
    )
    db_session.add(rulebook)
    await db_session.commit()
    return rulebook


async def test_reindex_ingests_every_rulebook_again(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.READY)
    await _add_rulebook(db_session, tmp_path, "Azul", "azul.pdf", RulebookStatus.FAILED)

    failed = await reindex(sessionmaker, tmp_path, FakeParser(ELEMENTS), FakeEmbedder())

    statuses = (await db_session.scalars(select(Rulebook.status).order_by(Rulebook.id))).all()
    chunks = (await db_session.scalars(select(Chunk))).all()
    assert failed == 0
    assert statuses == [RulebookStatus.READY, RulebookStatus.READY]
    assert len(chunks) == 2
    assert capsys.readouterr().out.splitlines()[-1] == "reindexed 2 rulebooks, 0 failed"


async def test_reindex_with_a_game_ingests_only_its_rulebooks(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    catan = await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.FAILED)
    await _add_rulebook(db_session, tmp_path, "Azul", "azul.pdf", RulebookStatus.FAILED)
    parser = FakeParser(ELEMENTS)

    await reindex(sessionmaker, tmp_path, parser, FakeEmbedder(), game_id=catan.game_id)

    assert [path.name for path, _ in parser.calls] == ["catan.pdf"]


async def test_reindex_prints_why_a_rulebook_failed(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.READY)
    parser = FailingParser(RuntimeError("parsing failed 3 times"))

    failed = await reindex(sessionmaker, tmp_path, parser, FakeEmbedder())

    assert failed == 1
    assert capsys.readouterr().out.splitlines() == [
        f"rulebook {rulebook.id} (catan.pdf): failed: parsing failed 3 times",
        "reindexed 1 rulebooks, 1 failed",
    ]


async def test_reindex_skips_a_rulebook_deleted_while_it_is_ingested(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.READY)
    parser = DeletingParser(sessionmaker, rulebook.id, ELEMENTS)

    failed = await reindex(sessionmaker, tmp_path, parser, FakeEmbedder())

    assert failed == 0
    assert capsys.readouterr().out.splitlines() == [
        f"rulebook {rulebook.id}: deleted, skipped",
        "reindexed 0 rulebooks, 0 failed",
    ]


async def test_reindex_with_reparse_gives_the_parser_no_stored_markdown(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path, "Catan", "catan.pdf", RulebookStatus.READY)
    rulebook.markdown = "<!-- page 1 -->\n\n# Setup\n"
    await db_session.commit()
    parser = FakeParser(ELEMENTS)

    await reindex(sessionmaker, tmp_path, parser, FakeEmbedder(), reparse=True)

    assert parser.calls == [(tmp_path / "catan.pdf", None)]


def test_parser_reads_the_game_option() -> None:
    assert _parser().parse_args(["reindex", "--game", "3"]).game == 3
    assert _parser().parse_args(["reindex"]).game is None


def test_parser_reads_the_eval_ingest_command() -> None:
    assert _parser().parse_args(["eval-ingest"]).command == "eval-ingest"


def test_parser_reads_the_eval_command() -> None:
    assert _parser().parse_args(["eval"]).command == "eval"


def test_parser_reads_the_eval_text_command() -> None:
    assert _parser().parse_args(["eval-text"]).command == "eval-text"


def test_parser_reads_the_reparse_option() -> None:
    assert _parser().parse_args(["reindex", "--reparse"]).reparse is True
    assert _parser().parse_args(["reindex"]).reparse is False
    assert _parser().parse_args(["eval-ingest", "--reparse"]).reparse is True
    assert _parser().parse_args(["eval-ingest"]).reparse is False


def test_parser_reads_the_parser_option() -> None:
    assert _parser().parse_args(["eval-ingest", "--parser", "llm"]).parser == "llm"
    assert _parser().parse_args(["eval", "--parser", "docling"]).parser == "docling"
    assert _parser().parse_args(["eval"]).parser is None


def test_parser_reads_the_compare_option() -> None:
    assert _parser().parse_args(["eval", "--compare"]).compare is True
    assert _parser().parse_args(["eval"]).compare is False


def test_parser_rejects_compare_with_a_parser() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(["eval", "--compare", "--parser", "llm"])


def test_eval_settings_point_at_the_parsers_own_database() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://bg:secret@localhost:5432/bg_assistant",
        eval_database_name="bg_assistant_eval",
        pdf_parser="docling",
    )

    eval_settings = _eval_settings(settings, "llm")

    assert (eval_settings.database_url, eval_settings.pdf_parser) == (
        "postgresql+psycopg://bg:secret@localhost:5432/bg_assistant_eval_llm",
        "llm",
    )


def test_cli_runs_as_a_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"], capture_output=True, text=True
    )

    assert result.returncode == 0
    assert "eval-ingest" in result.stdout
