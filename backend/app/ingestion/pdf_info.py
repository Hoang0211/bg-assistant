from pathlib import Path
from typing import cast

import pymupdf
from pymupdf import FileDataError

from app.errors import RuleViolationError


class InvalidPdfError(RuleViolationError):
    """The upload is not a PDF we can read."""


def read_page_count(data: bytes) -> int:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            if doc.needs_pass:
                raise InvalidPdfError("the PDF is password-protected")
            page_count: int = doc.page_count
            return page_count
    except FileDataError as exc:
        raise InvalidPdfError("the file is not a readable PDF") from exc


def page_texts(path: Path) -> list[str]:
    """Each page's text layer, in page order; a scanned page's is empty or nearly so."""
    with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
        return [cast(str, page.get_text()) for page in doc.pages()]


def low_text_pages(path: Path, min_chars: int) -> list[int]:
    return [
        number
        for number, text in enumerate(page_texts(path), start=1)
        if len(text.strip()) < min_chars
    ]


def render_page(path: Path, page: int, long_side_px: int) -> bytes:
    """Render one page (numbered from 1) as a PNG whose longer side is `long_side_px` pixels."""
    with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
        pdf_page = doc[page - 1]
        zoom = long_side_px / max(pdf_page.rect.width, pdf_page.rect.height)
        matrix = pymupdf.Matrix(zoom, zoom)  # type: ignore[no-untyped-call]
        png: bytes = pdf_page.get_pixmap(matrix=matrix).tobytes("png")
        return png
