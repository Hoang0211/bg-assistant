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
