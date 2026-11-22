"""How much of each PDF page's text layer the LLM parser's Markdown kept, and what it added."""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Rulebook
from app.ingestion.markdown_elements import split_pages
from app.ingestion.pdf_info import page_texts

# Letters and digits, with an apostrophe inside a word ("player's") kept.
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


@dataclass(frozen=True)
class PageOverlap:
    page: int
    pdf_words: int  # in the page's text layer
    missing: Counter[str]  # text-layer words the Markdown doesn't have
    added: Counter[str]  # Markdown words the text layer doesn't have

    @property
    def kept(self) -> float:
        """The share of the text layer's words that the Markdown has."""
        return 1 - self.missing.total() / self.pdf_words


@dataclass(frozen=True)
class RulebookOverlap:
    filename: str
    page_count: int
    pages: list[PageOverlap]  # only the pages with a text layer to compare with


def _words(text: str) -> Counter[str]:
    # A word hyphenated at a line break in the text layer is one word in the Markdown.
    text = text.lower().replace("’", "'").replace("-\n", "")
    return Counter(_WORD.findall(text))


def compare_page(page: int, pdf_text: str, markdown: str) -> PageOverlap:
    """Compare a page's words, ignoring case and Markdown symbols, which aren't words."""
    pdf = _words(pdf_text)
    parsed = _words(markdown)
    return PageOverlap(page, pdf.total(), missing=pdf - parsed, added=parsed - pdf)


def compare_rulebook(pdf_texts: list[str], markdown: str, min_chars: int) -> list[PageOverlap]:
    """Compare each page whose text layer has at least `min_chars` and some words in them.

    A scanned page has no text layer, and one of symbols or unreadable glyphs has no words, so
    neither has anything to compare with.
    """
    pages = split_pages(markdown)
    overlaps = [
        compare_page(number, text, pages.get(number, ""))
        for number, text in enumerate(pdf_texts, start=1)
        if len(text.strip()) >= min_chars
    ]
    return [overlap for overlap in overlaps if overlap.pdf_words]


async def rulebook_overlaps(
    session: AsyncSession, rulebooks_dir: Path, min_chars: int
) -> list[RulebookOverlap]:
    """Compare every rulebook's stored Markdown with its PDF; one with none has kept nothing."""
    rows = await session.execute(
        select(Rulebook.filename, Rulebook.storage_path, Rulebook.markdown).order_by(Rulebook.id)
    )
    overlaps: list[RulebookOverlap] = []
    for filename, storage_path, markdown in rows:
        texts = page_texts(rulebooks_dir / storage_path)
        pages = compare_rulebook(texts, markdown or "", min_chars)
        overlaps.append(RulebookOverlap(filename, len(texts), pages))
    return overlaps


def least_kept_first(rulebooks: list[RulebookOverlap]) -> list[tuple[str, PageOverlap]]:
    """Every checked page with its rulebook's filename, the page that kept least first."""
    pages = [(rulebook.filename, page) for rulebook in rulebooks for page in rulebook.pages]
    return sorted(pages, key=lambda item: item[1].kept)


def _share(missing: int, total: int) -> str:
    return f"{1 - missing / total:.0%}" if total else "–"


def _rulebook_row(rulebook: RulebookOverlap) -> str:
    pdf_words = sum(page.pdf_words for page in rulebook.pages)
    missing = sum(page.missing.total() for page in rulebook.pages)
    added = sum(page.added.total() for page in rulebook.pages)
    checked = len(rulebook.pages)
    kept = _share(missing, pdf_words)
    return (
        f"| {rulebook.filename} | {checked} of {rulebook.page_count} | {kept} "
        f"| {added if checked else '–'} |"
    )


def format_text_report(rulebooks: list[RulebookOverlap], min_chars: int, now: datetime) -> str:
    """Each rulebook's kept share and added words, then every checked page, least kept first."""
    lines = [
        f"# Text kept by the LLM parser: {now:%Y-%m-%d %H:%M}",
        "",
        "- Each page's Markdown is compared with the PDF's text layer as lower-case words;"
        " Markdown symbols and page markers aren't words.",
        "- Kept: the share of the text layer's words the Markdown has, so a low share means"
        " dropped text. Added: the Markdown's words the text layer doesn't have: changed or"
        " invented text, or text read from a picture that has no text layer.",
        f"- A page with under {min_chars} characters in its text layer (scanned or nearly"
        " blank), or with no words in it, has nothing to compare with and isn't checked.",
        "",
        "| Rulebook | Pages checked | Kept | Added words |",
        "| --- | --: | --: | --: |",
        *[_rulebook_row(rulebook) for rulebook in rulebooks],
        "",
        "## Pages, least kept first",
        "",
        "| Rulebook | Page | Text-layer words | Kept | Added words |",
        "| --- | --: | --: | --: | --: |",
        *[
            f"| {filename} | {page.page} | {page.pdf_words} | {page.kept:.0%} "
            f"| {page.added.total()} |"
            for filename, page in least_kept_first(rulebooks)
        ],
    ]
    return "\n".join(lines) + "\n"
