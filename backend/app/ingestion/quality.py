from dataclasses import dataclass

from app.ingestion.elements import Element


@dataclass(frozen=True)
class ParseReport:
    """How well a rulebook parsed, for the warnings the UI shows."""

    chunk_count: int
    empty_pages: list[int]  # no text kept: the page is blank, or holds only pictures


def build_report(elements: list[Element], chunk_count: int, page_count: int) -> ParseReport:
    # A sentence joined across a page break has text on every page from its first to its last.
    pages_with_text = {
        page
        for element in elements
        for page in range(element.page, (element.last_page or element.page) + 1)
    }
    return ParseReport(
        chunk_count=chunk_count,
        empty_pages=[page for page in range(1, page_count + 1) if page not in pages_with_text],
    )
