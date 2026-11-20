"""The rulebook parsers ingestion can use; the `pdf_parser` setting picks one."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.ingestion.elements import Element
from app.ingestion.llm_parser import parse_pdf_to_markdown
from app.ingestion.markdown_elements import markdown_to_elements
from app.ingestion.parse_process import parse_in_process
from app.ingestion.pdf_info import low_text_pages
from app.llm.base import LLMProvider, create_llm_provider


@dataclass(frozen=True)
class ParsedRulebook:
    """A parsed rulebook's elements, and what the parse found out along the way."""

    elements: list[Element]
    new_markdown: str | None = None  # Markdown this parse made, to store with the rulebook
    ocr_pages: list[int] = field(default_factory=list)  # read with OCR


class RulebookParser(Protocol):
    # Sections with fewer tokens are merged into a neighbouring section.
    chunk_min_tokens: int

    async def parse(self, path: Path, page_count: int, markdown: str | None) -> ParsedRulebook:
        """Parse a rulebook PDF; `markdown` is the copy an earlier parse stored, if any."""
        ...


class FakeParser:
    """Returns the same elements for every rulebook and records each call, for tests."""

    def __init__(
        self, elements: list[Element], new_markdown: str | None = None, chunk_min_tokens: int = 80
    ) -> None:
        self._elements = elements
        self._new_markdown = new_markdown
        self.chunk_min_tokens = chunk_min_tokens
        self.calls: list[tuple[Path, str | None]] = []  # the path and the stored Markdown

    async def parse(self, path: Path, page_count: int, markdown: str | None) -> ParsedRulebook:
        self.calls.append((path, markdown))
        return ParsedRulebook(self._elements, new_markdown=self._new_markdown)


class DoclingParser:
    """Docling's layout model, in a child process; pages with little text are read with OCR."""

    def __init__(self, settings: Settings) -> None:
        self.chunk_min_tokens = settings.chunk_min_tokens
        self._settings = settings

    async def parse(self, path: Path, page_count: int, markdown: str | None) -> ParsedRulebook:
        elements = await asyncio.to_thread(
            parse_in_process,
            path,
            self._settings.parse_attempts,
            self._settings.parse_timeout_seconds,
        )
        ocr_pages = await asyncio.to_thread(low_text_pages, path, self._settings.ocr_min_page_chars)
        return ParsedRulebook(elements, ocr_pages=ocr_pages)


class LlmParser:
    """A vision model that writes each page as Markdown; a stored copy is reused for free."""

    def __init__(self, settings: Settings, llm: LLMProvider) -> None:
        # Its headings are the rulebook's real section titles, so only scraps are merged.
        self.chunk_min_tokens = settings.markdown_chunk_min_tokens
        self._llm = llm

    async def parse(self, path: Path, page_count: int, markdown: str | None) -> ParsedRulebook:
        if markdown is not None:
            return ParsedRulebook(markdown_to_elements(markdown))

        new_markdown = await parse_pdf_to_markdown(path, page_count, self._llm)
        return ParsedRulebook(markdown_to_elements(new_markdown), new_markdown=new_markdown)


def create_parser(settings: Settings) -> RulebookParser:
    """The parser the settings choose: Docling, or the LLM parser."""
    if settings.pdf_parser == "llm":
        return LlmParser(settings, create_llm_provider(settings))
    return DoclingParser(settings)
