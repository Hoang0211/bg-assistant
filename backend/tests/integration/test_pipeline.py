import logging
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chunk, ChunkType, Game, Rulebook, RulebookStatus
from app.ingestion.elements import Element, ElementKind
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.parsers import FakeParser
from app.ingestion.pipeline import ingest_rulebook
from tests.helpers import DeletingParser, FailingParser, add_text_page

RULE = (
    "Players take turns in clockwise order. "
    "On your turn, roll the dice, collect resources, then trade with others and build."
)
ELEMENTS = [Element(ElementKind.HEADING, "Setup", 1), Element(ElementKind.PARAGRAPH, RULE, 1)]
MARKDOWN = f"<!-- page 1 -->\n\n# Setup\n\n{RULE}\n"
# Page 0 breaks the chunks' page_start >= 1 check, so saving them fails.
BAD_ELEMENTS = [Element(ElementKind.PARAGRAPH, "Each player takes five cards.", 0)]


async def _add_rulebook(
    db_session: AsyncSession, tmp_path: Path, markdown: str | None = None
) -> Rulebook:
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
        markdown=markdown,
    )
    db_session.add(rulebook)
    await db_session.commit()
    return rulebook


async def test_ingest_rulebook_stores_the_chunks_and_the_report(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)

    await ingest_rulebook(db_session, rulebook.id, tmp_path, FakeParser(ELEMENTS), FakeEmbedder())

    await db_session.refresh(rulebook)
    [chunk] = (await db_session.scalars(select(Chunk))).all()

    assert rulebook.status == RulebookStatus.READY
    assert rulebook.parse_report == {"chunk_count": 1, "empty_pages": [2]}
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

    await ingest_rulebook(db_session, rulebook.id, tmp_path, FakeParser(ELEMENTS), FakeEmbedder())

    messages = [record.getMessage() for record in caplog.records]
    assert messages[0] == f"ingesting rulebook {rulebook.id} (rules.pdf, 2 pages)"
    assert messages[1].startswith(f"rulebook {rulebook.id} ready: 1 chunks in ")
    assert len(messages) == 2


async def test_ingest_rulebook_replaces_the_old_chunks(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    await ingest_rulebook(db_session, rulebook.id, tmp_path, FakeParser(ELEMENTS), FakeEmbedder())
    new_elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Each player takes five cards.", 1),
    ]

    await ingest_rulebook(
        db_session, rulebook.id, tmp_path, FakeParser(new_elements), FakeEmbedder()
    )

    contents = (await db_session.scalars(select(Chunk.content))).all()
    assert contents == ["Setup\n\nEach player takes five cards."]


async def test_ingest_rulebook_gives_the_chunks_the_rulebooks_current_game(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    other_game = Game(name="Other game")
    db_session.add(other_game)
    await db_session.flush()
    # Moved behind the session's back, like a PATCH during the parse: the loaded rulebook
    # still has its old game.
    await db_session.execute(
        update(Rulebook).where(Rulebook.id == rulebook.id).values(game_id=other_game.id),
        execution_options={"synchronize_session": False},
    )

    await ingest_rulebook(db_session, rulebook.id, tmp_path, FakeParser(ELEMENTS), FakeEmbedder())

    assert await db_session.scalar(select(Rulebook.status)) == RulebookStatus.READY
    assert list(await db_session.scalars(select(Chunk.game_id))) == [other_game.id]


async def test_ingest_rulebook_merges_sections_under_the_chunk_minimum(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    elements = [
        Element(ElementKind.HEADING, "Setup", 1),
        Element(ElementKind.PARAGRAPH, "Roll the dice.", 1),
        Element(ElementKind.HEADING, "Scoring", 1),
        Element(ElementKind.PARAGRAPH, "The most points wins.", 1),
    ]

    # Each section is a few tokens, under the chunk_min_tokens setting of 20.
    await ingest_rulebook(db_session, rulebook.id, tmp_path, FakeParser(elements), FakeEmbedder())

    paths = (await db_session.scalars(select(Chunk.section_path).order_by(Chunk.id))).all()
    assert paths == ["Setup"]


async def test_ingest_rulebook_stores_the_parsers_new_markdown(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)

    await ingest_rulebook(
        db_session, rulebook.id, tmp_path, FakeParser(ELEMENTS, MARKDOWN), FakeEmbedder()
    )

    await db_session.refresh(rulebook)
    assert rulebook.markdown == MARKDOWN


async def test_ingest_rulebook_gives_the_parser_the_stored_markdown(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path, markdown=MARKDOWN)
    parser = FakeParser(ELEMENTS)

    await ingest_rulebook(db_session, rulebook.id, tmp_path, parser, FakeEmbedder())

    assert parser.calls == [(tmp_path / "rules.pdf", MARKDOWN)]


async def test_ingest_rulebook_with_reparse_gives_the_parser_no_stored_markdown(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path, markdown=MARKDOWN)
    parser = FakeParser(ELEMENTS)

    await ingest_rulebook(db_session, rulebook.id, tmp_path, parser, FakeEmbedder(), reparse=True)

    assert parser.calls == [(tmp_path / "rules.pdf", None)]


async def test_ingest_rulebook_keeps_the_stored_markdown_when_the_parser_returns_none(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path, markdown=MARKDOWN)

    await ingest_rulebook(db_session, rulebook.id, tmp_path, FakeParser(ELEMENTS), FakeEmbedder())

    await db_session.refresh(rulebook)
    assert rulebook.markdown == MARKDOWN


async def test_ingest_rulebook_saves_the_error_when_parsing_fails(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    parser = FailingParser(RuntimeError("OPENAI_API_KEY isn't set; add it to backend/.env"))

    await ingest_rulebook(db_session, rulebook.id, tmp_path, parser, FakeEmbedder())

    await db_session.refresh(rulebook)
    assert (rulebook.status, rulebook.error) == (
        RulebookStatus.FAILED,
        "OPENAI_API_KEY isn't set; add it to backend/.env",
    )


async def test_ingest_rulebook_keeps_the_old_chunks_when_saving_fails(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    await ingest_rulebook(db_session, rulebook.id, tmp_path, FakeParser(ELEMENTS), FakeEmbedder())

    await ingest_rulebook(
        db_session, rulebook.id, tmp_path, FakeParser(BAD_ELEMENTS), FakeEmbedder()
    )

    await db_session.refresh(rulebook)
    contents = (await db_session.scalars(select(Chunk.content))).all()
    assert rulebook.status == RulebookStatus.FAILED
    assert rulebook.parse_report == {"chunk_count": 1, "empty_pages": [2]}
    assert contents == [f"Setup\n\n{RULE}"]


async def test_ingest_rulebook_keeps_the_new_markdown_when_saving_fails(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)

    await ingest_rulebook(
        db_session, rulebook.id, tmp_path, FakeParser(BAD_ELEMENTS, MARKDOWN), FakeEmbedder()
    )

    await db_session.refresh(rulebook)
    assert (rulebook.status, rulebook.markdown) == (RulebookStatus.FAILED, MARKDOWN)


async def test_ingest_rulebook_skips_a_deleted_rulebook(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    rulebook = await _add_rulebook(db_session, tmp_path)
    await db_session.delete(rulebook)
    await db_session.commit()
    parser = FakeParser(ELEMENTS)

    await ingest_rulebook(db_session, rulebook.id, tmp_path, parser, FakeEmbedder())

    assert parser.calls == []


async def test_ingest_rulebook_skips_a_rulebook_deleted_while_it_is_parsed(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rulebook_id = (await _add_rulebook(db_session, tmp_path)).id
    caplog.set_level(logging.INFO, logger="app.ingestion.pipeline")
    # With new Markdown, so storing it meets the deleted rulebook too.
    parser = DeletingParser(sessionmaker, rulebook_id, ELEMENTS, MARKDOWN)

    await ingest_rulebook(db_session, rulebook_id, tmp_path, parser, FakeEmbedder())

    messages = [record.getMessage() for record in caplog.records]
    assert messages[-1] == f"rulebook {rulebook_id} was deleted while it was ingested"
    assert (await db_session.scalars(select(Chunk))).all() == []
