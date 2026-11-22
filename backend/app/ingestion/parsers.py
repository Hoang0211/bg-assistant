"""How ingestion parses a rulebook: the LLM parser, or a fake one in tests."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.ingestion.elements import Element
from app.ingestion.llm_parser import parse_pdf_to_markdown
from app.ingestion.markdown_elements import markdown_to_elements
from app.llm.base import LLMProvider, create_llm_provider


@dataclass(frozen=True)
class ParsedRulebook:
    """A parsed rulebook's elements, and the Markdown the parse made, if it made any."""

    elements: list[Element]
    new_markdown: str | None = None  # Markdown this parse made, to store with the rulebook


class RulebookParser(Protocol):
    async def parse(self, path: Path, page_count: int, markdown: str | None) -> ParsedRulebook:
        """Parse a rulebook PDF; `markdown` is the copy an earlier parse stored, if any."""
        ...


class FakeParser:
    """Returns the same elements for every rulebook and records each call, for tests."""

    def __init__(self, elements: list[Element], new_markdown: str | None = None) -> None:
        self._elements = elements
        self._new_markdown = new_markdown
        self.calls: list[tuple[Path, str | None]] = []  # the path and the stored Markdown

    async def parse(self, path: Path, page_count: int, markdown: str | None) -> ParsedRulebook:
        self.calls.append((path, markdown))
        return ParsedRulebook(self._elements, new_markdown=self._new_markdown)


class LlmParser:
    """A vision model that writes each page as Markdown; a stored copy is reused for free.

    Without a provider, it creates one on the first parse that calls the model, so the app
    starts without an API key, and only a rulebook that needs the model fails without one.
    """

    def __init__(self, settings: Settings, llm: LLMProvider | None = None) -> None:
        self._settings = settings
        self._llm = llm

    async def parse(self, path: Path, page_count: int, markdown: str | None) -> ParsedRulebook:
        if markdown is not None:
            return ParsedRulebook(markdown_to_elements(markdown))

        if self._llm is None:
            self._llm = create_llm_provider(self._settings)
        new_markdown = await parse_pdf_to_markdown(path, page_count, self._llm)
        return ParsedRulebook(markdown_to_elements(new_markdown), new_markdown=new_markdown)
