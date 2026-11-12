"""Ingest a generated rulebook end to end, with the real parser, embedder and database."""

from functools import partial
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk, Game, Rulebook, RulebookStatus
from app.ingestion.embedder import BgeEmbedder
from app.ingestion.parse_process import parse_in_process
from app.ingestion.pipeline import ingest_rulebook
from tests.helpers import add_text_page

# Each section is just over chunk_min_tokens (80), so each page becomes its own chunk.
SETUP = [
    "Place the board in the middle of the table and give each player the pieces of one colour.",
    "Shuffle the development cards and place them face down next to the board as a draw pile.",
    "Sort the resource cards into five piles by type and place them face up next to the bank.",
    "Each player places two settlements and two roads on the board, going round the table twice.",
    "The player who placed their second settlement last takes the first turn of the game.",
]
TRADING_LEFT = [
    "On your turn you may trade resources with the other players. Offer any number of cards "
    "and say what you want in return.",
    "Other players may make counter offers, but they may only trade with the player whose "
    "turn it is.",
]
TRADING_RIGHT = (
    "You may also trade with the bank at four to one, giving four cards of one resource for "
    "any one resource you choose."
)
EXAMPLE = "Example: Anna gives Ben two wool, and Ben gives Anna one ore in return."
SCORING = [
    "Each settlement is worth one victory point and each city is worth two victory points.",
    "The player with the longest road of at least five pieces earns two more victory points.",
    "The first player to reach ten victory points on their own turn wins the game immediately.",
    "Victory point cards stay hidden in your hand until you reveal them to win the game.",
    "If two players could win on the same turn, only the player whose turn it is wins.",
]


def _add_two_column_page(doc: pymupdf.Document) -> None:
    page = doc.new_page()
    page.insert_text((72, 72), "Trading", fontsize=20, fontname="hebo")
    top = 92
    for paragraph in TRADING_LEFT:
        box = pymupdf.Rect(72, top, 290, top + 90)  # type: ignore[no-untyped-call]
        assert page.insert_textbox(box, paragraph, fontsize=11) >= 0
        top += 90
    right = pymupdf.Rect(305, 92, 523, 182)  # type: ignore[no-untyped-call]
    assert page.insert_textbox(right, TRADING_RIGHT, fontsize=11) >= 0
    example = pymupdf.Rect(305, 192, 523, 252)  # type: ignore[no-untyped-call]
    page.draw_rect(example, color=(0, 0, 0), fill=(0.9, 0.9, 0.9), width=0.8)
    assert page.insert_textbox(example + (6, 6, -6, -6), EXAMPLE, fontsize=10, fontname="heit") >= 0


def _add_scanned_page(doc: pymupdf.Document, heading: str, paragraphs: list[str]) -> None:
    scan = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(scan, heading, paragraphs)
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=scan[0].get_pixmap(dpi=200))  # type: ignore[no-untyped-call]


async def test_ingest_rulebook_chunks_each_layout_by_section(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    add_text_page(doc, "Setup", SETUP)
    _add_two_column_page(doc)
    _add_scanned_page(doc, "Scoring", SCORING)
    doc.save(tmp_path / "rules.pdf")  # type: ignore[no-untyped-call]
    game = Game(name="Catan")
    db_session.add(game)
    await db_session.flush()
    rulebook = Rulebook(
        game_id=game.id,
        filename="rules.pdf",
        storage_path="rules.pdf",
        page_count=3,
        sha256="a" * 64,
    )
    db_session.add(rulebook)
    await db_session.commit()
    settings = get_settings()
    embedder = BgeEmbedder(settings.embedding_model)

    await ingest_rulebook(
        db_session,
        rulebook.id,
        tmp_path,
        partial(
            parse_in_process,
            attempts=settings.parse_attempts,
            timeout_seconds=settings.parse_timeout_seconds,
        ),
        embedder,
    )

    await db_session.refresh(rulebook)
    chunks = (await db_session.scalars(select(Chunk).order_by(Chunk.id))).all()
    assert rulebook.status == RulebookStatus.READY
    assert rulebook.parse_report == {"chunk_count": 3, "ocr_pages": [3], "empty_pages": []}
    assert [(chunk.section_path, chunk.page_start, chunk.page_end) for chunk in chunks] == [
        ("Setup", 1, 1),
        ("Trading", 2, 2),
        ("Scoring", 3, 3),
    ]
    assert [chunk.content for chunk in chunks] == [
        "\n\n".join(["Setup", *SETUP]),
        "\n\n".join(["Trading", *TRADING_LEFT, TRADING_RIGHT, EXAMPLE]),
        "\n\n".join(["Scoring", *SCORING]),
    ]
    assert list(chunks[1].embedding) == pytest.approx(
        embedder.embed_documents([chunks[1].content])[0], abs=1e-4
    )
