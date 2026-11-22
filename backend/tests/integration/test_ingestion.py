"""Ingest a generated rulebook end to end, with scripted model replies and the real embedder."""

from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk, Game, Rulebook, RulebookStatus
from app.ingestion.embedder import BgeEmbedder
from app.ingestion.parsers import LlmParser
from app.ingestion.pipeline import ingest_rulebook
from app.llm.fake import FakeLLMProvider
from tests.helpers import add_text_page

SETUP = [
    "Place the board in the middle of the table and give each player the pieces of one colour.",
    "Shuffle the development cards and place them face down next to the board as a draw pile.",
]
TRADING = [
    "On your turn you may trade resources with the other players.",
    "> **Example:** Anna gives Ben two wool, and Ben gives Anna one ore in return.",
]
SCORING = [
    "Each settlement is worth one victory point and each city is worth two victory points.",
    "The first player to reach ten victory points on their own turn wins the game immediately.",
]
# What the model writes for each page, in order.
PAGES = [("Setup", SETUP), ("Trading", TRADING), ("Scoring", SCORING)]


async def test_ingest_rulebook_stores_the_markdown_and_chunks_each_page_by_section(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for heading, _ in PAGES:
        add_text_page(doc, heading, ["The model's reply is scripted."])
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
    llm = FakeLLMProvider(["\n\n".join([f"# {heading}", *text]) for heading, text in PAGES])
    embedder = BgeEmbedder(settings.embedding_model)

    await ingest_rulebook(db_session, rulebook.id, tmp_path, LlmParser(settings, llm), embedder)

    await db_session.refresh(rulebook)
    chunks = (await db_session.scalars(select(Chunk).order_by(Chunk.id))).all()
    assert rulebook.status == RulebookStatus.READY
    assert rulebook.parse_report == {"chunk_count": 3, "empty_pages": []}
    assert rulebook.markdown is not None and rulebook.markdown.startswith("<!-- page 1 -->")
    assert [(chunk.section_path, chunk.page_start, chunk.page_end) for chunk in chunks] == [
        ("Setup", 1, 1),
        ("Trading", 2, 2),
        ("Scoring", 3, 3),
    ]
    assert [chunk.content for chunk in chunks] == [
        "\n\n".join([heading, *text]) for heading, text in PAGES
    ]
    assert list(chunks[1].embedding) == pytest.approx(
        embedder.embed_documents([chunks[1].content])[0], abs=1e-4
    )
