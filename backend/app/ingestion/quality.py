from dataclasses import dataclass

from app.ingestion.elements import Element


@dataclass(frozen=True)
class ParseReport:
    """How well a rulebook parsed, for the warnings the UI shows."""

    chunk_count: int
    ocr_pages: list[int]  # read with OCR, so the text may have recognition errors
    empty_pages: list[int]  # no text kept: the page has none, or it was all inside pictures


def build_report(
    elements: list[Element], chunk_count: int, page_count: int, ocr_pages: list[int]
) -> ParseReport:
    pages_with_text = {element.page for element in elements}
    return ParseReport(
        chunk_count=chunk_count,
        ocr_pages=ocr_pages,
        empty_pages=[page for page in range(1, page_count + 1) if page not in pages_with_text],
    )
