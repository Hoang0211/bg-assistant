import asyncio
import logging
import time
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk, Rulebook, RulebookStatus
from app.ingestion.chunker import ChunkLimits, TextChunk, chunk_elements
from app.ingestion.elements import Element
from app.ingestion.embedder import Embedder
from app.ingestion.parsers import RulebookParser
from app.ingestion.quality import build_report

logger = logging.getLogger(__name__)


def _chunk_and_embed(
    elements: list[Element], min_tokens: int, embedder: Embedder
) -> tuple[list[TextChunk], list[list[float]]]:
    settings = get_settings()
    limits = ChunkLimits(
        min_tokens=min_tokens,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    chunks = chunk_elements(elements, embedder.count_tokens, limits)
    vectors = embedder.embed_documents([chunk.content for chunk in chunks])
    return chunks, vectors


async def mark_failed(session: AsyncSession, rulebook_id: int, error: Exception) -> None:
    await session.execute(
        update(Rulebook)
        .where(Rulebook.id == rulebook_id)
        .values(status=RulebookStatus.FAILED, error=str(error))
    )
    await session.commit()


async def ingest_rulebook(
    session: AsyncSession,
    rulebook_id: int,
    upload_dir: Path,
    parser: RulebookParser,
    embedder: Embedder,
) -> None:
    """Parse, chunk and embed a rulebook, replacing its chunks; any error marks it as failed.

    New Markdown from the parser is stored as soon as the parse ends, so a later failure doesn't
    lose it; a parse that returns none leaves the stored copy as it is.
    """
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
        parsed = await parser.parse(
            upload_dir / rulebook.storage_path, rulebook.page_count, rulebook.markdown
        )
        if parsed.new_markdown is not None:
            # An UPDATE, not the loaded rulebook, so it changes nothing if the rulebook was
            # deleted during the parse.
            await session.execute(
                update(Rulebook)
                .where(Rulebook.id == rulebook_id)
                .values(markdown=parsed.new_markdown)
            )
            await session.commit()

        chunks, vectors = await asyncio.to_thread(
            _chunk_and_embed, parsed.elements, parser.chunk_min_tokens, embedder
        )
        report = build_report(parsed.elements, len(chunks), rulebook.page_count, parsed.ocr_pages)
        # Lock the rulebook until the commit, so a move waits and another ingestion of it can't
        # write its chunks at the same time; and read its game now, not from before the parse.
        game_id = await session.scalar(
            select(Rulebook.game_id).where(Rulebook.id == rulebook_id).with_for_update()
        )
        if game_id is None:
            logger.info("rulebook %d was deleted while it was ingested", rulebook_id)
            return

        await session.execute(delete(Chunk).where(Chunk.rulebook_id == rulebook_id))
        session.add_all(
            Chunk(
                rulebook_id=rulebook_id,
                game_id=game_id,
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
        await mark_failed(session, rulebook_id, error)
