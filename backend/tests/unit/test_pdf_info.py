import pytest
from pymupdf import mupdf

from app.ingestion.pdf_info import InvalidPdfError, read_page_count
from tests.helpers import make_pdf


def test_read_page_count_returns_the_number_of_pages() -> None:
    assert read_page_count(make_pdf(3)) == 3


def test_read_page_count_rejects_bytes_that_are_not_a_pdf() -> None:
    with pytest.raises(InvalidPdfError, match="not a readable PDF"):
        read_page_count(b"not a pdf")


def test_read_page_count_rejects_empty_bytes() -> None:
    with pytest.raises(InvalidPdfError, match="not a readable PDF"):
        read_page_count(b"")


def test_read_page_count_rejects_a_password_protected_pdf() -> None:
    data = make_pdf(1, encryption=mupdf.PDF_ENCRYPT_AES_256, user_pw="user", owner_pw="owner")
    with pytest.raises(InvalidPdfError, match="password-protected"):
        read_page_count(data)
