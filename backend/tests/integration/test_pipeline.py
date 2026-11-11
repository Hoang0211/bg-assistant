import logging
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, ChunkType, Game, Rulebook, RulebookStatus
from app.ingestion.elements import Element, ElementKind
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.parse_process import ParseFailedError
from app.ingestion.pipeline import ingest_rulebook
from tests.helpers import add_text_page

RULE = (
    "Players take turns in clockwise order. "
    "On your turn, roll the dice, collect resources, then trade with others and build."
)
ELEMENTS = [Element(ElementKind.HEADING, "Setup", 1), Element(ElementKind.PARAGRAPH, RULE, 1)]


async def _add_rulebook(db_session: AsyncSession, tmp_path: Path) -> Rulebook:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", [RULE])
    doc.new_page()
    doc.save(tmp_path / "rules.pdf")  # type: ignore[no-untyped-call]

    game = Game(name="Catan")
    db_session.add(game)
    await db_session.flush()
    rulebook = Rulebook(
        game_id=game.id,
        filename="rules.pdf",
        storage_path="rules.pdf",
        page_count=2,
        sha256="a" * 64,
    )
    db_session.add(rulebook)
    await db_session.commit()
    return rulebook


async def test_ingest_rulebook_stores_the_chunks_and_the_report(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)

    await ingest_rulebook(db_session, rulebook.id, tmp_path, lambda path: ELEMENTS, FakeEmbedder())

    await db_session.refresh(rulebook)
    [chunk] = (await db_session.scalars(select(Chunk))).all()

    assert rulebook.status == RulebookStatus.READY
    assert rulebook.parse_report == {"chunk_count": 1, "ocr_pages": [2], "empty_pages": [2]}
    assert (chunk.game_id, chunk.section_path, chunk.chunk_type) == (
        rulebook.game_id,
        "Setup",
        ChunkType.SECTION,
    )
    assert (chunk.page_start, chunk.page_end, chunk.content) == (1, 1, f"Setup\n\n{RULE}")
    assert list(chunk.embedding) == pytest.approx(
        FakeEmbedder().embed_query(chunk.content), abs=1e-6
    )


async def test_ingest_rulebook_logs_its_progress(
    db_session: AsyncSession, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    caplog.set_level(logging.INFO, logger="app.ingestion.pipeline")

    await ingest_rulebook(db_session, rulebook.id, tmp_path, lambda path: ELEMENTS, FakeEmbedder())

    messages = [record.getMessage() for record in caplog.records]
    assert messages[0] == f"ingesting rulebook {rulebook.id} (rules.pdf, 2 pages)"
    assert messages[1].startswith(f"rulebook {rulebook.id} ready: 1 chunks in ")
    assert len(messages) == 2


async def test_ingest_rulebook_replaces_the_old_chunks(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    await ingest_rulebook(db_session, rulebook.id, tmp_path, lambda path: ELEMENTS, FakeEmbedder())
    new_elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Each player takes five cards.", 1),
    ]

    await ingest_rulebook(
        db_session, rulebook.id, tmp_path, lambda path: new_elements, FakeEmbedder()
    )

    contents = (await db_session.scalars(select(Chunk.content))).all()
    assert contents == ["Setup\n\nEach player takes five cards."]


async def test_ingest_rulebook_saves_the_error_when_parsing_fails(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)

    def fail(path: Path) -> list[Element]:
        raise ParseFailedError("parsing failed 3 times; the backend log has the details")

    await ingest_rulebook(db_session, rulebook.id, tmp_path, fail, FakeEmbedder())

    await db_session.refresh(rulebook)
    assert (rulebook.status, rulebook.error) == (
        RulebookStatus.FAILED,
        "parsing failed 3 times; the backend log has the details",
    )


async def test_ingest_rulebook_keeps_the_old_chunks_when_saving_fails(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    await ingest_rulebook(db_session, rulebook.id, tmp_path, lambda path: ELEMENTS, FakeEmbedder())
    # Page 0 breaks the chunks' page_start >= 1 check, so saving fails after the old chunks
    # were deleted.
    bad_elements = [Element(ElementKind.PARAGRAPH, "Each player takes five cards.", 0)]

    await ingest_rulebook(
        db_session, rulebook.id, tmp_path, lambda path: bad_elements, FakeEmbedder()
    )

    await db_session.refresh(rulebook)
    contents = (await db_session.scalars(select(Chunk.content))).all()
    assert rulebook.status == RulebookStatus.FAILED
    assert rulebook.parse_report == {"chunk_count": 1, "ocr_pages": [2], "empty_pages": [2]}
    assert contents == [f"Setup\n\n{RULE}"]


async def test_ingest_rulebook_skips_a_deleted_rulebook(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    await db_session.delete(rulebook)
    await db_session.commit()
    parsed: list[Path] = []

    def parse(path: Path) -> list[Element]:
        parsed.append(path)
        return ELEMENTS

    await ingest_rulebook(db_session, rulebook.id, tmp_path, parse, FakeEmbedder())

    assert parsed == []
