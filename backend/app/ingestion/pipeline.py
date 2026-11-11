import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk, Rulebook, RulebookStatus
from app.ingestion.chunker import ChunkLimits, TextChunk, chunk_elements
from app.ingestion.elements import Element
from app.ingestion.embedder import Embedder
from app.ingestion.pdf_info import low_text_pages
from app.ingestion.quality import ParseReport, build_report

logger = logging.getLogger(__name__)


def _process(
    path: Path, page_count: int, parse: Callable[[Path], list[Element]], embedder: Embedder
) -> tuple[list[TextChunk], list[list[float]], ParseReport]:
    settings = get_settings()
    limits = ChunkLimits(
        min_tokens=settings.chunk_min_tokens,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    elements = parse(path)
    chunks = chunk_elements(elements, embedder.count_tokens, limits)
    vectors = embedder.embed_documents([chunk.content for chunk in chunks])
    ocr_pages = low_text_pages(path, settings.ocr_min_page_chars)
    report = build_report(elements, len(chunks), page_count, ocr_pages)
    return chunks, vectors, report


async def ingest_rulebook(
    session: AsyncSession,
    rulebook_id: int,
    upload_dir: Path,
    parse: Callable[[Path], list[Element]],
    embedder: Embedder,
) -> None:
    """Parse, chunk and embed a rulebook, replacing its chunks; any error marks it as failed."""
    rulebook = await session.get(Rulebook, rulebook_id)
    if rulebook is None:
        logger.info("rulebook %d was deleted before it was ingested", rulebook_id)
        return

    logger.info(
        "ingesting rulebook %d (%s, %d pages)",
        rulebook_id,
        rulebook.filename,
        rulebook.page_count,
    )
    start = time.perf_counter()
    rulebook.status = RulebookStatus.PROCESSING
    rulebook.error = None
    await session.commit()

    try:
        chunks, vectors, report = await asyncio.to_thread(
            _process, upload_dir / rulebook.storage_path, rulebook.page_count, parse, embedder
        )
        await session.execute(delete(Chunk).where(Chunk.rulebook_id == rulebook_id))
        session.add_all(
            Chunk(
                rulebook_id=rulebook_id,
                game_id=rulebook.game_id,
                section_path=chunk.section_path,
                chunk_type=chunk.chunk_type,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                content=chunk.content,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        )
        rulebook.parse_report = asdict(report)
        rulebook.status = RulebookStatus.READY
        await session.commit()
        logger.info(
            "rulebook %d ready: %d chunks in %.0f s",
            rulebook_id,
            len(chunks),
            time.perf_counter() - start,
        )
    except Exception as error:
        logger.exception("ingesting rulebook %d failed", rulebook_id)
        # After a rollback the loaded rulebook is expired, and reading it would need a lazy
        # load, so the failure is saved with an UPDATE instead.
        await session.rollback()
        await session.execute(
            update(Rulebook)
            .where(Rulebook.id == rulebook_id)
            .values(status=RulebookStatus.FAILED, error=str(error))
        )
        await session.commit()
